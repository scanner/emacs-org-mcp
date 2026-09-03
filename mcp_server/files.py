#!/usr/bin/env python
#
"""
Loose org files as a searchable corpus.

The task, journal and project tools encode a set of conventions: a tasks.org
with named sections, a directory of dated journal files, one file per project.
Any other org file in the org directory is unreachable by all of them --
archived work, design notes, a scratch file of half-finished thinking. That is
the material an open-ended search across years is most likely to want, and the
material least likely to have been filed under a convention.

It is also the only capability here that transfers. Another org-mode
installation may have no tasks.org and no journal directory at all, only .org
files in arbitrary places, and search is the one thing that still works there.

**A record is a heading plus its own body, not its subtree.** The alternative
counts every deep term again in each of its ancestors, and BM25 over
overlapping documents ranks a long ancestor above the heading that actually
answers the query. Splitting this way means the ancestors of a nested heading
hold no text of their own, so they are dropped: a heading with nothing under it
but more headings is structure, and its children carry the content.

Three file shapes decide the rest of the parsing, and each breaks a different
naive split. A file may have no headings at all, in which case the file itself
is the record. It may open with text before its first heading, which belongs to
the file rather than to any heading and would otherwise be lost. And it need
not start at level one -- a document written entirely at `**` and `***` is
ordinary.

The file's own name is indexed with every record it holds. A file named
`2024.03.11-queue-migration-design.org` states its subject where its headings
only cover the parts, so a search for the subject should find it.
"""

# system imports
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# project imports
from mcp_server.config import global_state, logger
from mcp_server.results import Record
from mcp_server.search import SearchDoc
from mcp_server.validation import HEADING_RE, scan_block_state

# =============================================================================
# Constants
# =============================================================================

# Org's own archive convention: a heading moved out of tasks.org lands in
# tasks.org_archive. Treated as a suffix rather than a named file so it works
# for whatever files an installation happens to have.
ARCHIVE_SUFFIX = "_archive"

ORG_SUFFIX = ".org"

# Files that live beside org files without being content: our own backups,
# Emacs tilde backups, and Emacs lock and autosave files. A long-lived org
# directory accumulates these in numbers comparable to the real files, and
# an arbitrary search root is worse.
JUNK_SUFFIXES = (".bak", "~")

# Largest file read into the corpus. Bounds what a mistyped search root can
# cost, and skips anything that is an org file only by extension.
MAX_FILE_BYTES = 2 * 1024 * 1024

# Longest heading path rendered on a result line, in headings. Notes files
# nest five or more deep, which is unreadable rendered in full.
MAX_PATH_PARTS = 3


# =============================================================================
# Records
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class OrgRecord:
    """
    One heading of one org file, with the text belonging to it.

    Attributes:
        path: The file this came from
        headline: The heading's own text, or the file's name for the text
            above the first heading
        content: The lines under that heading and above the next one, of any
            level. Never includes a descendant heading's text.
        level: Star count, or 0 for the text above the first heading
        heading_path: Ancestor headings, outermost first, for display
        line: 1-based line the heading sits on, which is what the record's
            link points at
        is_archive: Whether this came from an org archive file, in which case
            the work it describes is finished or abandoned
        modified: The file's modification time, ISO to the minute
    """

    path: Path
    headline: str
    content: str = ""
    level: int = 0
    heading_path: list[str] = field(default_factory=list)
    line: int = 1
    is_archive: bool = False
    modified: str = ""

    ###########################################################################
    #
    @property
    def display_path(self) -> str:
        """
        Return the heading path, trimmed to something that fits a line.

        Returns:
            The ancestor headings joined by `>`, elided in the middle when
            deeper than :data:`MAX_PATH_PARTS`. Empty for a top-level record.

        Note:
            The outermost and innermost headings are the ones kept. The
            outermost says which part of the file this is and the innermost is
            the immediate context; the levels between are the ones a reader
            can infer.
        """
        parts = self.heading_path
        if len(parts) > MAX_PATH_PARTS:
            parts = [parts[0], "…", *parts[-(MAX_PATH_PARTS - 1) :]]

        return " > ".join(parts)

    ###########################################################################
    #
    @property
    def ref(self) -> str:
        """
        Return an org link that opens this record in Emacs.

        Returns:
            `file:<path>::<line>`, which org opens at that line.

        Note:
            This is not merely an identifier, it is the route back to the
            content: there is no get tool for a loose org file the way there
            is for a task, so a caller follows a result up by opening its
            link. It therefore has to survive being read off a result line,
            which is why the whole link is rendered rather than a path the
            caller would reassemble.

            A line rather than org's `::*Heading` search, which finds the
            first heading of that name in the file. Generic subsection
            headings repeat -- an archive of twenty tasks has twenty
            `Description` headings -- so a name would open the wrong one.
        """
        return f"file:{tilde_path(self.path)}::{self.line}"


###############################################################################
#
def tilde_path(path: Path) -> str:
    """
    Render a path with the home directory as `~`.

    Args:
        path: Any path

    Returns:
        The path with `$HOME` replaced by `~`, unchanged if it lies
        elsewhere. This is the form org links use and the form these files
        already contain.
    """
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


# =============================================================================
# Reading files
# =============================================================================


###############################################################################
#
def is_org_file(name: str) -> bool:
    """
    Report whether a filename names org content.

    Args:
        name: A bare filename, without its directory

    Returns:
        True for `.org` files and for org's `<name>_archive` siblings.

    Note:
        Archive files have to pass a filter whose whole job is rejecting
        unusual extensions, which is why the check is written as a convention
        rather than as a list of known archives. They are finished work, not
        clutter.
    """
    if name.startswith(".") or name.startswith("#"):
        return False
    if name.endswith(JUNK_SUFFIXES):
        return False

    return name.endswith(ORG_SUFFIX) or name.endswith(ARCHIVE_SUFFIX)


###############################################################################
#
def walk_org_files(roots: list[Path]) -> Iterator[Path]:
    """
    Find every org file under the given roots.

    Args:
        roots: Directories to walk. One that does not exist yields nothing.

    Yields:
        Paths to org files, in a stable order.

    Note:
        Walks without following symlinks, so a link pointing at an ancestor
        cannot send this round forever, and prunes dot-directories, which is
        what keeps a root containing a git repository from reading its object
        store.

        A root given twice, or one nested inside another, yields each file
        once: the same document appearing twice would be counted twice by the
        ranking and shown twice in the results.
    """
    seen: set[Path] = set()

    for root in roots:
        if not root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(
                name for name in dirnames if not name.startswith(".")
            )

            for name in sorted(filenames):
                if not is_org_file(name):
                    continue

                path = Path(dirpath) / name
                resolved = path.resolve()
                if resolved in seen:
                    continue

                seen.add(resolved)
                yield path


###############################################################################
#
def read_org_file(path: Path) -> str | None:
    """
    Read an org file, refusing the ones not worth reading.

    Args:
        path: The file to read

    Returns:
        Its text, or None when the file is too large, not text, or unreadable.

    Note:
        A file is measured before it is opened, so an oversized one costs a
        stat rather than its own size in memory. Anything that is not UTF-8 is
        skipped rather than read with replacement characters: it is an org
        file by extension only, and indexing its bytes would put noise in the
        rankings for every other search.
    """
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            logger.debug(
                "search: skipping %s, over %d bytes", path, MAX_FILE_BYTES
            )
            return None

        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("search: skipping %s, %s", path, exc)
        return None


# =============================================================================
# Splitting
# =============================================================================


###############################################################################
#
def split_records(text: str, path: Path) -> list[OrgRecord]:
    """
    Split an org file into one record per heading.

    Args:
        text: The file's content
        path: The file it came from, used for the record's identity

    Returns:
        Records in document order. A heading holding nothing but further
        headings is omitted, since its text lives in its children and it would
        otherwise match on its title alone and return nothing to read.

    Note:
        Heading-like lines inside `#+begin_.../#+end_...` blocks are not
        headings. Org itself disagrees, which is the bug
        :func:`~mcp_server.validation.escape_headings_in_blocks` exists to
        repair on write -- but on read the author's meaning is what a search
        should return, and a file this server did not write may never have
        been through that repair.

        Text above the first heading becomes a record of its own, since a
        document that opens with a paragraph of context puts its whole
        subject there. Files with no headings at all get the same treatment.
    """
    is_archive = path.name.endswith(ARCHIVE_SUFFIX)
    modified = file_modified(path)

    def build(
        headline: str, level: int, ancestors: list[str], line: int
    ) -> OrgRecord:
        return OrgRecord(
            path=path,
            headline=headline,
            content="",
            level=level,
            heading_path=list(ancestors),
            line=line,
            is_archive=is_archive,
            modified=modified,
        )

    records: list[OrgRecord] = []

    # The file's own name stands in as the headline for text above the first
    # heading, which belongs to the file rather than to any heading.
    current = build(path.name, 0, [], 1)
    body: list[str] = []

    # Ancestors as (level, text), deepest last. A file need not start at level
    # one and need not descend one level at a time, so this pops by level
    # rather than assuming the parent is the previous heading.
    stack: list[tuple[int, str]] = []

    for number, line, inside in scan_block_state(text.split("\n")):
        match = None if inside else HEADING_RE.match(line)
        if not match:
            body.append(line)
            continue

        current.content = "\n".join(body).strip()
        if current.content:
            records.append(current)

        level = len(match.group(1))
        headline = match.group(2).strip()

        while stack and stack[-1][0] >= level:
            stack.pop()

        current = build(headline, level, [text for _, text in stack], number)
        stack.append((level, headline))
        body = []

    current.content = "\n".join(body).strip()
    if current.content:
        records.append(current)

    return records


###############################################################################
#
def file_modified(path: Path) -> str:
    """
    Return a file's modification time as a sortable timestamp.

    Args:
        path: The file to stat

    Returns:
        `YYYY-MM-DD HH:MM`, or empty when the file cannot be stat'd.

    Note:
        A loose org file carries no :CREATED: or :MODIFIED: drawer, so the
        filesystem is the only recency this corpus has. It is honest about
        what it means -- when the file last changed, not when this heading
        was written.

        This is the one place a real datetime appears, because `st_mtime` is
        an epoch float and something has to render it. It renders straight
        into the shape `normalize_sort_key` produces, so every sort key in
        every corpus is a string; see there for why they stay strings.
    """
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return ""

    return stamp.strftime("%Y-%m-%d %H:%M")


# =============================================================================
# The corpus
# =============================================================================


###############################################################################
###############################################################################
#
class FilesCorpus:
    """
    Org files under the configured search roots, as searchable documents.

    Implements :class:`~mcp_server.search.Corpus`. A root that does not exist
    is an empty corpus rather than an error, so this works in an installation
    that keeps nothing but a directory of notes.
    """

    ###########################################################################
    #
    def __init__(
        self,
        roots: list[Path] | None = None,
        skip: Callable[[Path], bool] | None = None,
        headline_only: bool = False,
    ) -> None:
        """
        Args:
            roots: Directories to walk, or None for the configured roots
            skip: Files to leave out, called with each candidate path. This is
                how the files that already have a typed tool are kept from
                being searched twice; see
                :func:`~mcp_server.corpus.owned_by_typed_corpus`.
            headline_only: Index only headings, so a query matches what a
                section is *about* rather than anything it mentions
        """
        self.roots = (
            roots if roots is not None else global_state.config.search_roots
        )
        self.skip = skip
        self.headline_only = headline_only

    ###########################################################################
    #
    def records(self) -> list[OrgRecord]:
        """
        Return every record in every file under the roots.

        Returns:
            Records in file and document order.
        """
        found: list[OrgRecord] = []

        for path in walk_org_files(self.roots):
            if self.skip and self.skip(path):
                continue

            text = read_org_file(path)
            if text is None:
                continue

            found.extend(split_records(text, path))

        return found

    ###########################################################################
    #
    def documents(self) -> list[SearchDoc]:
        """
        Return every record as a search document.

        Returns:
            One document per record.

        Note:
            The file's name joins the headline, so its terms are weighted the
            way a title is and every record in the file carries them. A dated
            design document is named for its subject and its headings often
            are not.
        """
        docs: list[SearchDoc] = []

        for record in self.records():
            name = record.path.name.replace("_", " ")
            docs.append(
                SearchDoc(
                    ref=record.ref,
                    headline=f"{record.headline} {name}".strip(),
                    body="" if self.headline_only else record.content,
                    sort_key=record.modified,
                    payload=record,
                )
            )

        return docs


###############################################################################
#
def org_record_to_record(record: OrgRecord) -> Record:
    """
    Adapt an org file record to the shared result envelope.

    Args:
        record: The record to adapt

    Returns:
        A :class:`Record` naming the file it came from.

    Note:
        The link goes on the line itself rather than being left in `ref`,
        which the envelope does not render. Every other adapter does the same
        with its own identifier -- a task repeats its CUSTOM_ID in the suffix
        -- and it matters more here, because a loose org file has no get tool
        to recover from a partial identifier.

        The heading path follows the link, since it is context rather than
        something to act on. It is what tells apart the several
        `Description` headings a result page can hold.

        Archived work is marked, because a hit in an archive is finished or
        abandoned and that changes how it should be read -- an archived
        heading describing an approach is not a description of what the code
        does now.
    """
    suffix = record.ref
    if path := record.display_path:
        suffix = f"{suffix} ({path})"

    return Record(
        ref=record.ref,
        prefix="[archived]" if record.is_archive else "",
        title=record.headline,
        suffix=suffix,
        content=record.content,
    )
