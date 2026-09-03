"""
Structural validation for org content submitted by MCP clients.

Every org document this server manages has a fixed root level, and every
topic inside that document has to be nested *below* it:

- A task is a single ``**`` heading; its subsections are ``***`` or deeper.
- A journal entry is a single ``**`` heading; its subsections are ``***`` or
  deeper (``*`` is the date heading that owns the whole file).
- A project file is a single ``*`` heading; its sections are ``**`` or deeper.

Content that violates this is not merely untidy -- it is destructive.  A stray
sibling heading either terminates the entry (so the rest of the submitted
content is silently discarded) or splits the file so that following entries
become invisible to the parser.  These validators reject such content up front
with an error that says exactly which line is wrong and how to fix it.

IMPORTANT: org only treats a leading ``*`` as a heading when it is at column
zero, and it does *not* exempt the inside of ``#+begin_.../#+end_...`` blocks.
A line like ``* Tasks`` inside a source block really does become a heading.
Org's own escape for this is a leading comma (``,* Tasks``), which Emacs
inserts automatically; :func:`escape_headings_in_blocks` does the same here so
callers can paste org samples into blocks without corrupting the file.
"""

# system imports
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

# =============================================================================
# Constants
# =============================================================================

# A heading is one or more stars at column zero followed by whitespace.  A bare
# "*" line, or "*emphasis*" starting at column zero, is not a heading.
HEADING_RE = re.compile(r"^(\*+)[ \t]+(.*)$")

# Block delimiters (#+begin_src, #+BEGIN_EXAMPLE, #+begin_quote, ...).  Org
# allows leading whitespace before the delimiter.
BLOCK_BEGIN_RE = re.compile(r"^[ \t]*#\+begin_(\S+)", re.IGNORECASE)
BLOCK_END_RE = re.compile(r"^[ \t]*#\+end_(\S+)", re.IGNORECASE)

# A line inside a block that org would otherwise read as a heading, and which
# therefore needs comma-escaping.
ESCAPABLE_RE = re.compile(r"^(\*+[ \t]|#\+)")

# A heading that has been pushed off column zero, e.g. " ** TODO Task".  Org
# reads it as body text, so it is swallowed into the *preceding* heading's
# subtree along with everything under it.
#
# IMPORTANT: this requires two or more stars.  A single indented "* " is a
# legitimate org list bullet and must not be flagged.
INDENTED_HEADING_RE = re.compile(r"^([ \t]+)(\*{2,})[ \t]+(.*)$")


# =============================================================================
# Heading Scanning
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass(frozen=True)
class OrgHeading:
    """A heading found while scanning submitted org content."""

    level: int  # Number of leading stars
    text: str  # Heading text with the stars stripped
    line_number: int  # 1-based line number within the scanned content

    ###########################################################################
    #
    @property
    def source(self) -> str:
        """The heading as it appears in the source content."""
        return f"{'*' * self.level} {self.text}".rstrip()


###############################################################################
#
def scan_block_state(lines: Iterable[str]) -> Iterator[tuple[int, str, bool]]:
    """
    Walk lines, saying which of them sit inside a block.

    Args:
        lines: The lines of an org document, without line endings

    Yields:
        `(line_number, line, inside)` for every line, numbered from 1.
        `inside` is True only for the lines *between* a `#+begin_...` and
        its matching `#+end_...`; the delimiters themselves are outside,
        which is what lets an escaping caller leave them alone.

    Note:
        A block ends only on the delimiter that matches the one that opened
        it, so a nested `#+begin_src` inside an example block is ordinary
        content rather than a second block.

        Anything scanning org line by line needs this, and each caller
        rewriting the state machine is how they drift apart -- one of them
        would eventually decide a heading inside a block was real.
    """
    open_block: str | None = None

    for idx, line in enumerate(lines, start=1):
        if open_block is None:
            if begin := BLOCK_BEGIN_RE.match(line):
                open_block = begin.group(1).lower()
            yield (idx, line, False)
            continue

        end = BLOCK_END_RE.match(line)
        if end and end.group(1).lower() == open_block:
            open_block = None
            yield (idx, line, False)
            continue

        yield (idx, line, True)


###############################################################################
#
def scan_headings(content: str) -> list[OrgHeading]:
    """
    Find every real org heading in ``content``.

    Args:
        content: Org-formatted text to scan

    Returns:
        List of headings in document order.

    Note:
        Lines inside ``#+begin_.../#+end_...`` blocks are skipped, because
        this function reports what the *author* meant.  Org itself would treat
        an unescaped heading inside a block as real -- that discrepancy is what
        :func:`escape_headings_in_blocks` exists to remove, and callers should
        escape before they scan.
    """
    headings: list[OrgHeading] = []

    for idx, line, inside in scan_block_state(content.split("\n")):
        if inside:
            continue

        if match := HEADING_RE.match(line):
            headings.append(
                OrgHeading(
                    level=len(match.group(1)),
                    text=match.group(2).strip(),
                    line_number=idx,
                )
            )

    return headings


###############################################################################
#
def find_indented_headings(content: str) -> list[OrgHeading]:
    """
    Find headings that have been pushed off column zero.

    Args:
        content: Org-formatted text to scan

    Returns:
        List of would-be headings that carry leading whitespace, in document
        order.  ``level`` is the star count they were presumably meant to have.

    Note:
        This is the signature of the 2026-08-23 data-loss incident.  A single
        leading space turns ``** TODO Task`` into body text, so org folds the
        whole task -- drawer, subsections and all -- into the *preceding*
        task's subtree.  The task then cannot be found, is omitted from
        listings, and a search for its text returns the task before it.  A
        subsequent full-replacement update of that preceding task overwrites
        the absorbed region and the task is gone.

        Only two-or-more-star lines are reported: a single indented ``*`` is a
        normal org list bullet.
    """
    headings: list[OrgHeading] = []

    for idx, line, inside in scan_block_state(content.split("\n")):
        if inside:
            continue

        if match := INDENTED_HEADING_RE.match(line):
            headings.append(
                OrgHeading(
                    level=len(match.group(2)),
                    text=match.group(3).strip(),
                    line_number=idx,
                )
            )

    return headings


###############################################################################
#
def _check_indentation(content: str, kind: str) -> None:
    """
    Raise if ``content`` contains a heading that is not at column zero.

    Args:
        content: Org-formatted text to check
        kind: Human name for the document, used in the error message

    Raises:
        ValueError: If any indented heading is found.
    """
    indented = find_indented_headings(content)
    if not indented:
        return

    listing = "\n".join(
        f"  line {h.line_number}: {' ' * 4}{h.source}\n"
        f"      remove the leading whitespace: {h.source}"
        for h in indented
    )
    raise ValueError(
        f"Invalid {kind} structure: {len(indented)} heading(s) are indented "
        f"instead of starting at column zero.\n\n{listing}\n\n"
        f"Org only treats '*' as a heading at column zero. An indented "
        f"heading becomes body text, so it and everything under it are "
        f"absorbed into the preceding heading and become unreachable."
    )


###############################################################################
#
def escape_headings_in_blocks(content: str) -> tuple[str, list[int]]:
    """
    Comma-escape heading-like lines inside ``#+begin_.../#+end_...`` blocks.

    Args:
        content: Org-formatted text that may contain literal org samples

    Returns:
        Tuple of (escaped content, 1-based line numbers that were escaped).

    Note:
        This is exactly what Emacs does when you type a ``*`` at column zero
        inside a source block.  Without it, ``* Tasks`` in a code sample
        becomes a real level-1 heading on the next parse, which splits the file
        and hides every entry that follows it.  Already-escaped lines
        (``,* ...``) are left alone.
    """
    lines = content.split("\n")
    escaped_lines: list[int] = []

    for number, line, inside in scan_block_state(lines):
        if inside and ESCAPABLE_RE.match(line):
            lines[number - 1] = f",{line}"
            escaped_lines.append(number)

    return ("\n".join(lines), escaped_lines)


# =============================================================================
# Error Reporting
# =============================================================================


###############################################################################
#
def _format_offenders(
    offenders: list[tuple[OrgHeading, str]], required_level: int
) -> str:
    """
    Render offending headings as an indented, line-numbered list.

    Args:
        offenders: List of (heading, explanation) pairs
        required_level: Minimum star count nested content must use

    Returns:
        Multi-line string listing each offender and its correction.
    """
    lines: list[str] = []
    for heading, why in offenders:
        fixed = f"{'*' * required_level} {heading.text}".rstrip()
        lines.append(f"  line {heading.line_number}: {heading.source}")
        lines.append(f"      {why} -- write it as: {fixed}")
    return "\n".join(lines)


###############################################################################
#
def _structure_error(
    kind: str,
    root_stars: str,
    child_stars: str,
    offenders: list[tuple[OrgHeading, str]],
    consequence: str,
) -> str:
    """
    Build the standard "bad heading levels" error message.

    Args:
        kind: Human name for the document ("task", "journal entry", "project")
        root_stars: The document's own heading level, e.g. ``**``
        child_stars: The shallowest legal nested level, e.g. ``***``
        offenders: List of (heading, explanation) pairs
        consequence: What would have happened had the write gone through

    Returns:
        A multi-line, actionable error message for the MCP client.
    """
    required_level = len(child_stars)
    return (
        f"Invalid {kind} structure: every heading below the "
        f"{root_stars} heading must be nested at {child_stars} or deeper.\n\n"
        f"{_format_offenders(offenders, required_level)}\n\n"
        f"{consequence}\n\n"
        f"Fix: add stars to the headings above so they are children of the "
        f"{root_stars} heading, then resubmit. If a line starting with '*' is "
        f"meant as literal text, put it inside a #+begin_example/#+end_example "
        f"block (the server comma-escapes those automatically)."
    )


# =============================================================================
# Document Validators
# =============================================================================


###############################################################################
#
def validate_task_entry(task_entry: str) -> str:
    """
    Validate and normalize a task entry submitted by a client.

    Args:
        task_entry: Complete org-formatted task entry

    Returns:
        The entry with heading-like lines inside blocks comma-escaped.

    Raises:
        ValueError: If the entry is not exactly one ``**`` heading whose
            subsections are all ``***`` or deeper.

    Note:
        Without this check the org parser keeps only the first ``**`` heading
        and everything after a stray sibling is silently discarded, while the
        write still reports success.
    """
    escaped, _ = escape_headings_in_blocks(task_entry)
    _check_indentation(escaped, "task")
    headings = scan_headings(escaped)

    if not headings:
        raise ValueError(
            "Invalid task structure: no heading found. A task entry must "
            "begin with a level-2 heading, e.g. '** TODO GH-123 Fix the bug'."
        )

    first = headings[0]
    if first.level != 2:
        raise ValueError(
            f"Invalid task structure: a task must begin with a level-2 "
            f"heading ('** TODO ...'), but line {first.line_number} is at "
            f"level {first.level}:\n\n"
            f"  {first.source}\n\n"
            f"Write it as: ** {first.text}"
        )

    offenders = [
        (
            h,
            (
                "a second level-2 heading starts a new task"
                if h.level == 2
                else f"level-{h.level} headings end the task entirely"
            ),
        )
        for h in headings[1:]
        if h.level <= 2
    ]

    if offenders:
        raise ValueError(
            _structure_error(
                kind="task",
                root_stars="**",
                child_stars="***",
                offenders=offenders,
                consequence=(
                    "Everything from the first offending line onward would be "
                    "silently dropped from the task, or split off into a "
                    "separate entry -- the write is being refused so that "
                    "content is not lost."
                ),
            )
        )

    return escaped


###############################################################################
#
def validate_journal_content(content: str, headline: str = "") -> str:
    """
    Validate and normalize the body of a journal entry.

    Args:
        content: Body content for the entry (bullets, prose, blocks)
        headline: The entry headline, checked for embedded newlines

    Returns:
        The content with heading-like lines inside blocks comma-escaped.

    Raises:
        ValueError: If the headline spans multiple lines, or the body contains
            a heading at level 1 or 2.

    Note:
        A ``*`` line in a journal body terminates the day's date heading; a
        ``**`` line becomes a *separate journal entry*.  Either way the entry
        the caller thought it was writing is silently truncated.
    """
    if "\n" in headline:
        raise ValueError(
            "Invalid journal entry: the headline must be a single line. "
            "Move the extra lines into the entry content."
        )

    escaped, _ = escape_headings_in_blocks(content)
    _check_indentation(escaped, "journal entry")
    offenders = [
        (
            h,
            (
                "a level-2 heading becomes a separate journal entry"
                if h.level == 2
                else f"a level-{h.level} heading ends the day's date section"
            ),
        )
        for h in scan_headings(escaped)
        if h.level <= 2
    ]

    if offenders:
        raise ValueError(
            _structure_error(
                kind="journal entry",
                root_stars="**",
                child_stars="***",
                offenders=offenders,
                consequence=(
                    "The entry body would be split at the first offending "
                    "line, orphaning everything after it -- the write is "
                    "being refused so that content is not lost."
                ),
            )
        )

    return escaped


###############################################################################
#
def validate_project_entry(project_entry: str) -> str:
    """
    Validate and normalize a complete project file submitted by a client.

    Args:
        project_entry: Complete org-formatted project file content

    Returns:
        The entry with heading-like lines inside blocks comma-escaped.

    Raises:
        ValueError: If the entry is not exactly one ``*`` heading whose
            sections are all ``**`` or deeper.

    Note:
        A project file holds exactly one project.  A second ``*`` heading makes
        everything after it invisible to the parser, which reads only the first
        level-1 heading in the file.
    """
    escaped, _ = escape_headings_in_blocks(project_entry)
    _check_indentation(escaped, "project")
    headings = scan_headings(escaped)

    if not headings:
        raise ValueError(
            "Invalid project structure: no heading found. A project file must "
            "begin with a level-1 heading, e.g. '* Booklore  :project:'."
        )

    first = headings[0]
    if first.level != 1:
        raise ValueError(
            f"Invalid project structure: a project file must begin with a "
            f"level-1 heading ('* Project Title'), but line "
            f"{first.line_number} is at level {first.level}:\n\n"
            f"  {first.source}\n\n"
            f"Write it as: * {first.text}"
        )

    offenders = [
        (h, "a second level-1 heading starts a new project file")
        for h in headings[1:]
        if h.level == 1
    ]

    if offenders:
        raise ValueError(
            _structure_error(
                kind="project",
                root_stars="*",
                child_stars="**",
                offenders=offenders,
                consequence=(
                    "Only the first level-1 heading is read as the project, so "
                    "everything after the offending line would become "
                    "unreachable -- the write is being refused so that content "
                    "is not lost."
                ),
            )
        )

    return escaped


###############################################################################
#
def validate_project_section_content(section_name: str, content: str) -> str:
    """
    Validate and normalize the body of a single project section.

    Args:
        section_name: Name of the ``**`` section being replaced
        content: New body content for that section

    Returns:
        The content with heading-like lines inside blocks comma-escaped.

    Raises:
        ValueError: If the body contains a heading at level 1 or 2.

    Note:
        Section bodies live under a ``**`` heading, so any nested heading must
        be ``***`` or deeper.  A ``**`` line would silently become a sibling
        section and a ``*`` line would start a second project.
    """
    escaped, _ = escape_headings_in_blocks(content)
    _check_indentation(escaped, f"project section '{section_name}'")
    offenders = [
        (
            h,
            (
                f"a level-2 heading becomes a sibling of '{section_name}', "
                "not part of it"
                if h.level == 2
                else "a level-1 heading starts a second project"
            ),
        )
        for h in scan_headings(escaped)
        if h.level <= 2
    ]

    if offenders:
        raise ValueError(
            _structure_error(
                kind=f"project section '{section_name}'",
                root_stars="**",
                child_stars="***",
                offenders=offenders,
                consequence=(
                    "The section body would be cut short at the first "
                    "offending line -- the write is being refused so that "
                    "content is not lost."
                ),
            )
        )

    return escaped
