#!/usr/bin/env python
#
"""
The one result envelope every list and search tool renders through.

Tasks, journal entries and projects are different shapes, but an agent reading
them wants the same three things from all of them: a bounded number of results,
enough per result to decide whether to fetch it, and an unambiguous way to ask
for the next page. Those concerns live here. What a record *looks like* stays
with the type that knows -- the adapter hands over a :class:`Record` with its
columns already rendered.

This module deliberately imports nothing from ``tasks``, ``journal`` or
``projects``. They depend on it, not the other way round, so the adapters sit
in those modules and the envelope stays free of the record types.

Three detail levels:

``index``
    One line per record. What a listing costs is then predictable from the
    number of records alone.
``snippet``
    The index line plus the lines that matched, with a line of context either
    side. This is the level that usually answers the question outright, which
    is why it is the default for search and why it exists at all -- an index
    line says *which* record matched but never *why*, so every search would
    otherwise cost a second, blind fetch.
``full``
    The whole record. Sizes are skewed enough -- journal entries run to a
    median of 11 lines and a maximum of 927 -- that this is worth asking for
    deliberately rather than receiving by default.
"""

# system imports
import re
from dataclasses import dataclass, field
from typing import Literal

# =============================================================================
# Constants
# =============================================================================

DetailLevel = Literal["index", "snippet", "full"]

DETAIL_LEVELS: tuple[str, ...] = ("index", "snippet", "full")

# Results returned when the caller does not ask for a specific number.
DEFAULT_LIMIT = 50

# Lines of context shown either side of a matching line at ``snippet``.
SNIPPET_CONTEXT = 1

# Most snippet lines any single record may contribute. Without this a record
# that matches a common word fifty times would cost fifty lines on its own,
# which is the unbounded behaviour the level exists to avoid.
MAX_SNIPPET_LINES = 4

# Longest a title may run before it is trimmed. Only the title is trimmed --
# the prefix and suffix carry status and identity, which are what a follow-up
# call needs.
MAX_TITLE = 96


# =============================================================================
# Records
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class Record:
    """
    One result, with its type-specific columns already rendered.

    The adapter that builds this knows what a task or a journal entry should
    look like; the envelope only decides how many to show and what to say
    around them.

    Attributes:
        ref: Identifier a follow-up call can use, e.g. a ``:CUSTOM_ID:`` or a
            journal date and time. This is what makes a result actionable.
        prefix: Leading columns, such as a status or a timestamp.
        title: The headline. The only part that gets trimmed when a line is
            too long, since prefix and suffix carry what a follow-up needs.
        suffix: Trailing identity, such as ``(task-gh-28)``.
        tags: Org tags, rendered as ``:a:b:`` when present.
        content: The record body. Never emitted at ``index``; used for the
            size hint, for snippets, and in full at ``full``.
        score: Relevance score, when ranked. Reserved so that adding ranking
            later does not change this shape.
        matched_terms: Query terms this record matched.
        total_terms: Query terms searched for.
    """

    ref: str
    prefix: str = ""
    title: str = ""
    suffix: str = ""
    tags: list[str] = field(default_factory=list)
    content: str = ""
    score: float | None = None
    matched_terms: int | None = None
    total_terms: int | None = None

    ###########################################################################
    #
    @property
    def size(self) -> tuple[int, int]:
        """
        Return the body's size as (lines, characters).

        Returns:
            Line and character counts. An empty body is zero lines, not one.
        """
        if not self.content:
            return (0, 0)
        return (self.content.count("\n") + 1, len(self.content))


# =============================================================================
# Rendering
# =============================================================================


###############################################################################
#
def format_size(lines: int, chars: int) -> str:
    """
    Render a body's size compactly enough to sit on a result line.

    Args:
        lines: Line count
        chars: Character count

    Returns:
        A bracketed hint such as ``[47L 1.2k]``, or an empty string for an
        empty body.

    Note:
        This is what lets a caller decide whether fetching a record in full is
        worth it. Both numbers are given because lines predict how a record
        reads and characters predict what it costs.
    """
    if not lines:
        return ""

    if chars >= 1000:
        return f"[{lines}L {chars / 1000:.1f}k]"
    return f"[{lines}L {chars}c]"


###############################################################################
#
def snippet_lines(content: str, query: str) -> list[str]:
    """
    Return the lines of ``content`` that matched, with surrounding context.

    Args:
        content: The record body
        query: The query that produced this result

    Returns:
        Up to :data:`MAX_SNIPPET_LINES` lines, trimmed and de-duplicated, in
        document order. Empty when nothing matches.

    Note:
        Matching is case-insensitive substring, which is what the search
        functions currently do. When ranking arrives this should take the
        parsed query terms instead, so a snippet shows every term that hit
        rather than the raw string.
    """
    if not content or not query:
        return []

    lines = content.split("\n")
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    wanted: set[int] = set()
    for idx, line in enumerate(lines):
        if pattern.search(line):
            lo = max(0, idx - SNIPPET_CONTEXT)
            hi = min(len(lines), idx + SNIPPET_CONTEXT + 1)
            wanted.update(range(lo, hi))

    chosen = [lines[i].strip() for i in sorted(wanted) if lines[i].strip()]
    return chosen[:MAX_SNIPPET_LINES]


###############################################################################
#
def render_record(record: Record, number: int, query: str) -> str:
    """
    Render one record's index line.

    Args:
        record: The record to render
        number: Its position in the overall result set, 1-based
        query: The active query, used only to decide nothing here

    Returns:
        A single line.
    """
    title = record.title
    if len(title) > MAX_TITLE:
        title = title[: MAX_TITLE - 1].rstrip() + "…"

    tags = f" :{':'.join(record.tags)}:" if record.tags else ""
    size = format_size(*record.size)

    parts = [
        f"{number:>4}.",
        record.prefix,
        title,
        record.suffix,
        size,
        tags.strip(),
    ]
    return " ".join(p for p in parts if p)


###############################################################################
#
def render(
    records: list[Record],
    *,
    tool: str,
    header: str,
    detail: DetailLevel = "index",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    query: str = "",
    order: str = "",
    warnings: list[str] | None = None,
) -> str:
    """
    Render a page of results with a header, a body and a next-page hint.

    Args:
        records: The complete result set. Paging is applied here, so callers
            hand over everything they found and let the envelope bound it.
        tool: Name of the calling tool, so the next-page hint can name it
        header: What was listed or searched, e.g. ``Tasks`` or
            ``search_journal("compaction")``
        detail: One of ``index``, ``snippet`` or ``full``. ``snippet`` falls
            back to ``index`` when there is no query to match against, which
            is every list tool -- rejecting it instead would make a parameter's
            validity depend on which tool it was passed to.
        limit: Maximum records to render
        offset: Records to skip
        query: The active query, used to build snippets
        order: Ordering in effect, named in the header when given
        warnings: Lines that must reach the caller on *every* page, such as
            the report of tasks the parser cannot see. Callers must pass these
            rather than appending afterwards, because anything appended after
            the body can be paged past.

    Returns:
        The rendered page.

    Note:
        Paging is stateless offset and limit rather than a cursor: a cursor
        would imply server-side state and its invalidation, and there is no
        session here to hold it. The next call is stated in words because an
        agent reading this cannot be relied on to infer it.
    """
    warnings = warnings or []
    total = len(records)

    if detail == "snippet" and not query:
        detail = "index"

    lines: list[str] = []

    # Warnings go above the results. Anything below them can be paged past,
    # and the loudest of them reports tasks the parser has lost track of.
    if warnings:
        lines.extend(warnings)
        lines.append("")

    if total == 0:
        lines.append(f"{header} -- no results")
        return "\n".join(lines)

    if offset >= total:
        lines.append(
            f"{header} -- {total} result{'s' if total != 1 else ''}, "
            f"but offset {offset} is past the end"
        )
        return "\n".join(lines)

    page = records[offset : offset + limit]
    first, last = offset + 1, offset + len(page)

    shown = f"showing {first}-{last}" if total > len(page) else "showing all"
    ordering = f", order={order}" if order else ""
    title_line = (
        f"{header} -- {total} result{'s' if total != 1 else ''}, "
        f"{shown}{ordering}"
    )

    lines.append(title_line)
    lines.append("=" * min(len(title_line), 78))
    lines.append("")

    for idx, record in enumerate(page, start=first):
        lines.append(render_record(record, idx, query))

        match detail:
            case "snippet":
                lines.extend(
                    f"        > {line}"
                    for line in snippet_lines(record.content, query)
                )
            case "full":
                if record.content.strip():
                    lines.extend(
                        f"        {line}"
                        for line in record.content.rstrip().split("\n")
                    )
                    lines.append("")

    remaining = total - last
    if remaining > 0:
        lines.append("")
        lines.append(f"{remaining} more. Next: call {tool} with offset={last}")

    return "\n".join(lines)
