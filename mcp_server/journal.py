"""
Journal operations: data structure, parsing, CRUD, and formatting.
"""

# system imports
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# project imports
from mcp_server.config import global_state
from mcp_server.utils import (
    backup_file,
    format_simple_diff,
    get_current_timestamp,
    request_ediff_approval,
    write_file,
)

# NOTE: get_current_timestamp is imported for potential future use and
# to keep the import pattern consistent with tasks.py; currently unused
# but retained intentionally.
_ = get_current_timestamp


# =============================================================================
# Journal Data Structure
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class JournalEntry:
    """Represents a journal entry."""

    time: str  # HH:MM format
    headline: str  # Everything after time (ticket, summary, etc.)
    tags: list[str]  # Tags like :daily_summary:
    content: str  # Body content (bullet points)
    line_number: int  # Starting line in file
    file_date: str  # YYYYMMDD from filename

    ###########################################################################
    #
    def to_org(self) -> str:
        """Serialize entry back to org format."""
        tags_str = f" :{':'.join(self.tags)}:" if self.tags else ""
        lines = [f"** {self.time} {self.headline}{tags_str}"]
        if self.content.strip():
            lines.append(self.content.rstrip())
        return "\n".join(lines)


# =============================================================================
# Journal Operations (manual parsing - org-journal has different structure)
# =============================================================================


###############################################################################
#
def detect_journal_extension() -> str:
    """
    Detect the preferred journal file extension by examining existing files.

    Returns:
        ".org" if any existing journal file has that extension, "" otherwise

    Note:
        Ensures new journal files match the existing naming convention in the
        journal directory. Checks for YYYYMMDD.org pattern.
    """
    journal_dir = global_state.config.journal_dir
    if not journal_dir.exists():
        return ""
    # Check if any YYYYMMDD.org files exist
    for path in journal_dir.iterdir():
        if (
            path.suffix == ".org"
            and path.stem.isdigit()
            and len(path.stem) == 8
        ):
            return ".org"
    return ""


###############################################################################
#
def get_journal_path(target_date: date) -> Path:
    """
    Get journal file path for a date.

    Args:
        target_date: Date to get journal path for

    Returns:
        Path object for the journal file (YYYYMMDD or YYYYMMDD.org)

    Note:
        Checks for existing file with .org extension first, then without.
        Uses detected extension convention for new files.
    """
    base_path = global_state.config.journal_dir / target_date.strftime("%Y%m%d")

    # Check for existing file with .org extension first, then without
    org_path = base_path.with_suffix(".org")
    if org_path.exists():
        return org_path
    if base_path.exists():
        return base_path

    # File doesn't exist - use detected convention for new files
    ext = detect_journal_extension()
    return base_path.with_suffix(ext) if ext else base_path


###############################################################################
#
def parse_journal_entry(
    lines: list[str], start_idx: int, file_date: str
) -> tuple[JournalEntry, int]:
    """
    Parse a single journal entry starting at a specific line.

    Args:
        lines: All lines from the journal file
        start_idx: Line index where the entry starts
        file_date: Date string from the filename (YYYYMMDD)

    Returns:
        Tuple of (parsed JournalEntry, next_line_index)

    Raises:
        ValueError: If entry format is invalid

    Note:
        Expected format: ** HH:MM headline :tags:
        Parses until next heading or end of file.
    """
    match = re.match(
        r"^\*\*\s+(\d{2}:\d{2})\s+(.+?)(?:\s+:([^:]+(?::[^:]+)*):)?$",
        lines[start_idx],
    )
    if not match:
        raise ValueError(f"Invalid journal entry format at line {start_idx}")

    time = match.group(1)
    headline = match.group(2).strip()
    tags = match.group(3).split(":") if match.group(3) else []

    content_lines = []
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]
        if line.startswith("** ") or line.startswith("* "):
            break
        content_lines.append(line)
        i += 1

    return (
        JournalEntry(
            time=time,
            headline=headline,
            tags=tags,
            content="\n".join(content_lines),
            line_number=start_idx,
            file_date=file_date,
        ),
        i,
    )


###############################################################################
#
def parse_journal_entries(file_path: Path) -> list[JournalEntry]:
    """
    Parse all entries from a journal file.

    Args:
        file_path: Path to the journal file

    Returns:
        List of all JournalEntry objects found in the file

    Note:
        Returns empty list if file doesn't exist.
        Silently skips invalid entry formats.
    """
    if not file_path.exists():
        return []

    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    # Strip .org extension if present to get YYYYMMDD
    file_date = file_path.stem if file_path.suffix == ".org" else file_path.name

    entries = []
    i = 0

    while i < len(lines):
        if lines[i].startswith("** "):
            try:
                entry, i = parse_journal_entry(lines, i, file_date)
                entries.append(entry)
            except ValueError:
                i += 1
        else:
            i += 1

    return entries


###############################################################################
#
def create_journal_entry(
    target_date: date,
    time_str: str,
    headline: str,
    content: str,
    tags: list[str] | None = None,
) -> tuple[date, JournalEntry]:
    """
    Create or append a journal entry to a daily file.

    Args:
        target_date: Date for the journal entry
        time_str: Time in HH:MM format
        headline: Entry headline text
        content: Entry body content (bullet points)
        tags: Optional list of tags

    Returns:
        Tuple of (target_date, created_entry)

    Note:
        Creates new file with date heading if it doesn't exist.
        Appends to existing file if it exists.
        Creates backup before modifying existing files.
    """
    file_path = get_journal_path(target_date)
    tags = tags or []

    entry = JournalEntry(
        time=time_str,
        headline=headline,
        tags=tags,
        content=content,
        line_number=0,
        file_date=target_date.strftime("%Y%m%d"),
    )
    entry_text = entry.to_org()

    # Context: date + time (e.g., "20250107-1430")
    context_name = (
        f"{target_date.strftime('%Y%m%d')}-{time_str.replace(':', '')}"
    )

    # Request approval via ediff
    approved, final_entry_text = request_ediff_approval(
        old_content="",  # Empty for create
        new_content=entry_text,
        context_name=context_name,
    )

    if not approved:
        raise ValueError("User rejected journal entry creation")

    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8").rstrip()
        new_content = f"{existing}\n\n{final_entry_text}"
    else:
        date_heading = target_date.strftime("* %Y-%m-%d")
        new_content = f"{date_heading}\n\n{final_entry_text}"

    backup_path = backup_file(file_path)
    write_file(file_path, new_content)

    # Remove backup after successful write
    if backup_path != file_path and backup_path.exists():
        backup_path.unlink()

    return (target_date, entry)


###############################################################################
#
def find_journal_entry(
    file_path: Path,
    time_str: str,
    headline: str | None = None,
) -> JournalEntry:
    """
    Find a journal entry by time, using headline to disambiguate if needed.

    Args:
        file_path: Path to the journal file
        time_str: Time in HH:MM format to match
        headline: Optional headline substring to disambiguate when multiple
                  entries share the same time

    Returns:
        The matching JournalEntry

    Raises:
        ValueError: If no entry matches, or multiple entries match the time
                    and no headline was provided to disambiguate
    """
    entries = parse_journal_entries(file_path)
    matches = [e for e in entries if e.time == time_str]

    if not matches:
        raise ValueError(f"No journal entry found at time {time_str}")

    if len(matches) == 1:
        return matches[0]

    # Multiple entries at this time — use headline to disambiguate
    if headline:
        headline_matches = [
            e for e in matches if headline.lower() in e.headline.lower()
        ]
        if len(headline_matches) == 1:
            return headline_matches[0]
        if not headline_matches:
            raise ValueError(
                f"Multiple entries at {time_str} but none match "
                f"headline '{headline}'"
            )
        raise ValueError(
            f"Multiple entries at {time_str} match headline "
            f"'{headline}' — provide a more specific headline"
        )

    headlines = [e.headline for e in matches]
    raise ValueError(
        f"Multiple entries at {time_str}: {headlines}. "
        "Provide 'existing_headline' to disambiguate."
    )


###############################################################################
#
def update_journal_entry(
    file_path: Path,
    time_str: str,
    headline: str,
    content: str,
    tags: list[str] | None = None,
    existing_time: str | None = None,
    existing_headline: str | None = None,
) -> tuple[JournalEntry, JournalEntry, date]:
    """
    Update an existing journal entry, found by time and optional headline.

    Args:
        file_path: Path to the journal file
        time_str: New time in HH:MM format
        headline: New headline text
        content: New body content
        tags: Optional new tags list
        existing_time: Time of entry to update (defaults to time_str if not
                       provided)
        existing_headline: Headline substring to disambiguate if multiple
                          entries share the same time

    Returns:
        Tuple of (old_entry, new_entry, date)

    Note:
        Creates backup before modification.
        Replaces entry while preserving other entries.
    """
    lookup_time = existing_time or time_str
    old_entry = find_journal_entry(file_path, lookup_time, existing_headline)
    line_number = old_entry.line_number

    file_content = file_path.read_text(encoding="utf-8")
    lines = file_content.split("\n")

    entry_start = line_number
    entry_end = entry_start + 1

    while entry_end < len(lines):
        if lines[entry_end].startswith("** ") or lines[entry_end].startswith(
            "* "
        ):
            break
        entry_end += 1

    # Strip .org extension if present to get YYYYMMDD
    date_str = file_path.stem if file_path.suffix == ".org" else file_path.name

    tags = tags or []
    new_entry = JournalEntry(
        time=time_str,
        headline=headline,
        tags=tags,
        content=content,
        line_number=line_number,
        file_date=date_str,
    )

    old_entry_org = old_entry.to_org()
    new_entry_org = new_entry.to_org()
    context_name = f"{date_str}-{time_str.replace(':', '')}"

    # Request approval via ediff
    approved, final_entry_text = request_ediff_approval(
        old_content=old_entry_org,
        new_content=new_entry_org,
        context_name=context_name,
    )

    if not approved:
        raise ValueError("User rejected journal entry update")

    new_entry_lines = final_entry_text.split("\n")

    # Preserve blank line separator: if the old entry had a trailing blank
    # line before the next entry/heading, keep it so entries don't run
    # together.
    if entry_end < len(lines) and lines[entry_end - 1] == "":
        new_entry_lines.append("")

    new_lines = lines[:entry_start] + new_entry_lines + lines[entry_end:]

    backup_path = backup_file(file_path)
    write_file(file_path, "\n".join(new_lines))

    # Remove backup after successful write
    if backup_path != file_path and backup_path.exists():
        backup_path.unlink()

    # Parse date from filename (YYYYMMDD)
    target_date = date(
        int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
    )

    return (old_entry, new_entry, target_date)


###############################################################################
#
def search_journal(query: str, days_back: int = 30) -> list[JournalEntry]:
    """
    Search journal entries within recent days.

    Args:
        query: Search query string (case-insensitive)
        days_back: Number of days to search back (default 30)

    Returns:
        List of matching journal entries

    Note:
        Searches in both headline and content.
        Skips files that don't exist.
    """
    matches = []
    query_lower = query.lower()

    for i in range(days_back):
        target_date = date.today() - timedelta(days=i)
        file_path = get_journal_path(target_date)

        if file_path.exists():
            entries = parse_journal_entries(file_path)
            for entry in entries:
                searchable = f"{entry.headline} {entry.content}".lower()
                if query_lower in searchable:
                    matches.append(entry)

    return matches


# =============================================================================
# Journal Formatting
# =============================================================================


###############################################################################
#
def format_journal_create_result(target_date: date, entry: JournalEntry) -> str:
    """
    Format the result of a journal entry creation.

    Args:
        target_date: Date for which the entry was created
        entry: The created journal entry

    Returns:
        Formatted confirmation with entry content
    """
    lines = [
        f"✓ Journal Entry Created for {target_date.isoformat()}",
        "",
        entry.to_org(),
    ]
    return "\n".join(lines)


###############################################################################
#
def format_journal_update_result(
    old_entry: JournalEntry, new_entry: JournalEntry, target_date: date
) -> str:
    """
    Format the result of a journal entry update with diff.

    Args:
        old_entry: The entry before the update
        new_entry: The entry after the update
        target_date: Date of the journal file

    Returns:
        Formatted string with status, diff, and final content
    """
    lines = [
        f"✓ Journal Entry Updated for {target_date.isoformat()}",
        "",
        "Changes:",
        format_simple_diff(old_entry.to_org(), new_entry.to_org()),
        "",
        "Final:",
        new_entry.to_org(),
    ]
    return "\n".join(lines)


###############################################################################
#
def format_journal_list(entries: list[JournalEntry], date_str: str) -> str:
    """
    Format a list of journal entries for display.

    Args:
        entries: List of journal entries to format
        date_str: Date string for the header

    Returns:
        Formatted entry list with date header and entry summaries
    """
    if not entries:
        return f"No journal entries for {date_str}"

    lines = [f"Journal Entries for {date_str}", "=" * 30, ""]

    for entry in entries:
        tags = f" :{':'.join(entry.tags)}:" if entry.tags else ""
        lines.append(f"  {entry.time}  {entry.headline}{tags}")
        if entry.content.strip():
            content_preview = entry.content.strip().split("\n")[:2]
            for content_line in content_preview:
                lines.append(f"         {content_line}")

    return "\n".join(lines)


###############################################################################
#
def format_journal_detail(entry: JournalEntry) -> str:
    """
    Format a single journal entry in full detail.

    Args:
        entry: The journal entry to format

    Returns:
        Formatted entry with all metadata and complete content
    """
    tags = f" :{':'.join(entry.tags)}:" if entry.tags else ""

    lines = [
        f"{entry.time}  {entry.headline}{tags}",
        f"Date: {entry.file_date}",
        "",
        entry.to_org(),
    ]
    return "\n".join(lines)


# =============================================================================
# Serialization Helpers
# =============================================================================


###############################################################################
#
def journal_entry_to_dict(entry: JournalEntry) -> dict:
    """
    Convert journal entry to dictionary for JSON output.

    Args:
        entry: JournalEntry object to convert

    Returns:
        Dictionary with entry fields suitable for JSON serialization
    """
    return {
        "time": entry.time,
        "headline": entry.headline,
        "tags": entry.tags,
        "content": entry.content,
        "file_date": entry.file_date,
        "line_number": entry.line_number,
    }
