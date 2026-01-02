#!/usr/bin/env python3
"""
MCP Server for Emacs Org-Mode Tasks and Journal Management

Uses orgmunge for robust org-mode file manipulation.
Designed for use with Claude CLI/Code/Desktop to manage:
- ~/org/tasks.org (task tracking with Active/Completed sections)
- ~/org/journal/YYYYMMDD (daily journal entries)

Task and journal content format follows the conventions in ~/.claude/CLAUDE.md
"""

import difflib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from mcp.server import InitializationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, ServerCapabilities, TextContent, Tool
from orgmunge import Org
from orgmunge.classes import Heading

# =============================================================================
# Configuration
# =============================================================================

ORG_DIR = Path(os.environ.get("ORG_DIR", Path.home() / "org"))
TASKS_FILE = ORG_DIR / "tasks.org"
JOURNAL_DIR = Path(os.environ.get("JOURNAL_DIR", ORG_DIR / "journal"))
TODO_STATES = (v for k, v in Org.get_todos()["todo_states"].items())
DONE_STATES = (v for k, v in Org.get_todos()["done_states"].items())
ALL_STATES = tuple(list(TODO_STATES) + list(DONE_STATES))

# These are the properties we care about on a task in tasks.org
#
PROPERTIES = ("CUSTOM_ID", "ID", "CREATED", "MODIFIED", "CLOSED")

# Section names - configurable via environment variables
ACTIVE_SECTION = os.environ.get("ACTIVE_SECTION", "Tasks")
COMPLETED_SECTION = os.environ.get("COMPLETED_SECTION", "Completed Tasks")
HIGH_LEVEL_SECTION = os.environ.get(
    "HIGH_LEVEL_SECTION", "High Level Tasks (in order)"
)

server = Server("emacs-org-mode")

# =============================================================================
# Timestamp Utilities
# =============================================================================


###############################################################################
#
def format_org_timestamp(dt: datetime, active: bool = True) -> str:
    """
    Format a datetime as an org-mode timestamp.

    Args:
        dt: The datetime to format (should be naive, in local timezone)
        active: True for active timestamp <...>, False for inactive [...]

    Returns:
        Formatted org-mode timestamp string

    Examples:
        Active: <2025-12-26 Thu 01:45>
        Inactive: [2025-12-26 Thu 01:45]

    Note:
        Expects naive timestamps in the timezone of the running Emacs instance.
        Org-mode timestamps do not support timezone information.
    """
    # Format: <YYYY-MM-DD DDD HH:MM> or [YYYY-MM-DD DDD HH:MM]
    day_abbr = dt.strftime("%a")
    timestamp = dt.strftime(f"%Y-%m-%d {day_abbr} %H:%M")

    if active:
        return f"<{timestamp}>"
    else:
        return f"[{timestamp}]"


###############################################################################
#
def get_current_timestamp(active: bool = True) -> str:
    """
    Get current time as an org-mode timestamp.

    Args:
        active: True for active timestamp <...>, False for inactive [...]

    Returns:
        Current timestamp as org-mode formatted string

    Note:
        Uses local timezone without timezone information per org-mode spec.
    """
    return format_org_timestamp(datetime.now(), active=active)


# =============================================================================
# Plain Text Formatting Utilities
# =============================================================================


###############################################################################
#
def format_simple_diff(old_content: str, new_content: str) -> str:
    """
    Create a simple diff showing only changed lines with − and + markers.

    Args:
        old_content: Original content to compare from
        new_content: New content to compare against

    Returns:
        Formatted diff string with − for removed lines and + for added lines,
        or "(no changes)" if contents are identical
    """
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    if old_lines == new_lines:
        return "(no changes)"

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    diff_lines: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        match tag:
            case "equal":
                continue
            case "replace":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"− {line}")
                for line in new_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")
            case "delete":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"− {line}")
            case "insert":
                for line in new_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")

    return "\n".join(diff_lines) if diff_lines else "(no changes)"


###############################################################################
#
def format_task_update_result(
    old_task: "Task",
    new_content: str,
    moved: bool,
    old_section: str,
    new_section: str,
) -> str:
    """
    Format the result of a task update with diff.

    Args:
        old_task: The task before the update
        new_content: The updated task content
        moved: Whether the task moved between sections
        old_section: Original section name
        new_section: Target section name

    Returns:
        Formatted string with status, diff, and final content
    """
    lines = []

    if moved:
        lines.append(f"✓ Task Updated and Moved: {old_section} → {new_section}")
    else:
        lines.append(f"✓ Task Updated in {new_section}")

    lines.append("")
    lines.append("Changes:")
    lines.append(format_simple_diff(old_task.content, new_content))
    lines.append("")
    lines.append("Final:")
    lines.append(new_content)

    return "\n".join(lines)


###############################################################################
#
def format_task_create_result(section: str, task_content: str) -> str:
    """
    Format the result of a task creation.

    Args:
        section: Section where task was created
        task_content: Full org-mode content of the created task

    Returns:
        Formatted confirmation with task content
    """
    lines = [
        f"✓ Task Created in {section}",
        "",
        task_content,
    ]
    return "\n".join(lines)


###############################################################################
#
def format_journal_create_result(
    target_date: date, entry: "JournalEntry"
) -> str:
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
    old_entry: "JournalEntry", new_entry: "JournalEntry", target_date: date
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
def format_task_preview(
    old_task: "Task", new_content: str, old_section: str, new_section: str
) -> str:
    """
    Format a preview of task changes without modifying the file.

    Args:
        old_task: The existing task
        new_content: Proposed new content
        old_section: Current section name
        new_section: Target section name

    Returns:
        Formatted diff showing proposed changes
    """
    lines = []

    if old_section != new_section:
        lines.append(f"Preview: Task will move {old_section} → {new_section}")
    else:
        lines.append(f"Preview: Task in {new_section}")

    lines.append("")
    lines.append("Proposed changes:")
    lines.append(format_simple_diff(old_task.content, new_content))

    return "\n".join(lines)


###############################################################################
#
def format_journal_preview(
    old_entry: "JournalEntry", new_entry: "JournalEntry"
) -> str:
    """
    Format a preview of journal entry changes without modifying the file.

    Args:
        old_entry: The existing journal entry
        new_entry: Proposed new entry

    Returns:
        Formatted diff showing proposed changes
    """
    lines = [
        f"Preview: Journal entry at {old_entry.time} on {old_entry.file_date}",
        "",
        "Proposed changes:",
        format_simple_diff(old_entry.to_org(), new_entry.to_org()),
    ]
    return "\n".join(lines)


###############################################################################
#
def format_task_list(tasks: list["Task"], section: str) -> str:
    """
    Format a list of tasks for display.

    Args:
        tasks: List of tasks to format
        section: Section name for the header

    Returns:
        Formatted task list with section header and task summaries
    """
    if not tasks:
        return f"No tasks in {section}"

    lines = [f"{section}", "=" * len(section), ""]

    for task in tasks:
        ticket = f"[{task.ticket_id}] " if task.ticket_id else ""
        name_info = f" (#{task.custom_id})" if task.custom_id else ""
        lines.append(f"  {task.status}  {ticket}{task.headline}{name_info}")

    return "\n".join(lines)


###############################################################################
#
def format_journal_list(entries: list["JournalEntry"], date_str: str) -> str:
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
def format_task_detail(task: "Task") -> str:
    """
    Format a single task in full detail.

    Args:
        task: The task to format

    Returns:
        Formatted task with all metadata and complete content
    """
    ticket = f"[{task.ticket_id}] " if task.ticket_id else ""
    name_info = f"\n#+NAME: {task.custom_id}" if task.custom_id else ""

    lines = [
        f"{task.status}  {ticket}{task.headline}",
        f"Section: {task.section}{name_info}",
        "",
        task.content,
    ]
    return "\n".join(lines)


###############################################################################
#
def format_journal_detail(entry: "JournalEntry") -> str:
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


###############################################################################
#
def format_search_results(items: list, item_type: str) -> str:
    """
    Format search results with count and items.

    Args:
        items: List of tasks or journal entries
        item_type: Type label ("task" or "journal entry")

    Returns:
        Formatted search results with count and item summaries
    """
    count = len(items)
    lines = [f"Found {count} {item_type}{'s' if count != 1 else ''}", ""]

    if item_type == "task":
        for task in items:
            ticket = f"[{task.ticket_id}] " if task.ticket_id else ""
            lines.append(f"  {task.status}  {ticket}{task.headline}")
    else:
        for entry in items:
            tags = f" :{':'.join(entry.tags)}:" if entry.tags else ""
            lines.append(
                f"  {entry.time}  {entry.headline}{tags} ({entry.file_date})"
            )

    return "\n".join(lines)


###############################################################################
#
def format_move_result(
    headline: str, from_section: str, to_section: str
) -> str:
    """
    Format the result of moving a task between sections.

    Args:
        headline: Task headline
        from_section: Source section name
        to_section: Destination section name

    Returns:
        Formatted confirmation message
    """
    return f"✓ Task Moved: {from_section} → {to_section}\n  {headline}"


# =============================================================================
# Task Data Structure
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class Task:
    """Represents an org-mode task with its metadata."""

    custom_id: str  # The :CUSTOM_ID: identifier (e.g., "task-gh-28")
    headline: str  # The headline text (e.g., "GH-28 API for cloning...")
    status: str  # "TODO" or "DONE"
    section: str  # Which section this task is in
    content: str  # Full task content as org string (for output)
    id: str = ""  # The :ID: from :PROPERTIES: drawer (UUID)
    created: str = ""  # The :CREATED: timestamp (active, set on creation)
    modified: str = (
        ""  # The :MODIFIED: timestamp (inactive, updated on modification)
    )
    closed: str = ""  # The :CLOSED: timestamp (active, set when marked DONE)

    ###########################################################################
    #
    @property
    def ticket_id(self) -> str | None:
        """Extract GH/JIRA ticket ID from headline if present."""
        match = re.search(r"\b([A-Z]+-\d+)\b", self.headline)
        return match.group(1) if match else None


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
# Org File Operations (using orgmunge)
# =============================================================================


###############################################################################
#
def get_org() -> Org:
    """
    Load and return the Org object for the tasks file.

    Returns:
        Org object representing the tasks file

    Raises:
        FileNotFoundError: If tasks file does not exist
    """
    if not TASKS_FILE.exists():
        raise FileNotFoundError(f"Tasks file not found: {TASKS_FILE}")
    return Org(str(TASKS_FILE))


###############################################################################
#
def find_section(org: Org, section_name: str) -> Heading | None:
    """
    Find a top-level section heading by name.

    Args:
        org: The Org object to search in
        section_name: Name of the section to find

    Returns:
        The Heading object if found, None otherwise
    """
    for heading in org.root.children:
        if heading.headline.level == 1:
            title = (
                heading.headline.title
                if hasattr(heading.headline, "title")
                else str(heading.headline)
            )
            clean_title = title.replace("* ", "").strip()
            if clean_title == section_name:
                return heading
    return None


###############################################################################
#
def heading_to_org_string(heading: Heading) -> str:
    """
    Convert an orgmunge heading back to org-mode string format.

    Args:
        heading: The orgmunge Heading object to convert

    Returns:
        Org-mode formatted string representation of the heading

    Note:
        Recursively includes all child headings in the output.
    """
    lines = []

    # Build headline
    stars = "*" * heading.headline.level
    todo = f"{heading.headline.todo} " if heading.headline.todo else ""
    title = (
        heading.headline.title
        if hasattr(heading.headline, "title")
        else str(heading.headline)
    )
    tags = heading.headline.tags
    tags_str = f" :{':'.join(tags)}:" if tags else ""
    lines.append(f"{stars} {todo}{title}{tags_str}")

    # Add body if present
    if heading.body:
        lines.append(heading.body.rstrip())

    # Recursively add children
    for child in heading.children:
        lines.append(heading_to_org_string(child))

    return "\n".join(lines)


###############################################################################
#
def _properties(heading: Heading) -> SimpleNamespace:
    if hasattr(heading, "properties"):
        properties = SimpleNamespace(heading.properties)
    else:
        properties = SimpleNamespace()

    # For all expected PROPERTIES that are not set, we set them to `None`
    # NOTE: Properties set to `None` are not written back to the org-mode file
    #
    for prop in PROPERTIES:
        if not hasattr(properties, prop):
            properties.__dict__[prop] = None

    return properties


###############################################################################
#
def parse_tasks_in_section(
    section_heading: Heading | None, section_name: str
) -> list[Task]:
    """
    Parse tasks that are direct children of a section heading.

    Args:
        section_heading: The section heading to parse tasks from
        section_name: Name of the section (for Task metadata)

    Returns:
        List of Task objects found in the section
    """
    tasks: list[Task] = []

    if section_heading is None:
        return tasks

    for heading in section_heading.children:
        if heading.headline.level != 2:
            continue

        todo_state = heading.headline.todo
        if todo_state not in ALL_STATES:
            continue

        # Get properties from the :PROPERTIES: drawer
        custom_id = ""
        task_id = ""
        created = ""
        modified = ""
        closed = ""
        if hasattr(heading, "properties") and heading.properties:
            custom_id = heading.properties.get("CUSTOM_ID", "")
            task_id = heading.properties.get("ID", "")
            created = heading.properties.get("CREATED", "")
            modified = heading.properties.get("MODIFIED", "")
            closed = heading.properties.get("CLOSED", "")

        headline_text = (
            heading.headline.title
            if hasattr(heading.headline, "title")
            else str(heading.headline)
        )

        tasks.append(
            Task(
                custom_id=custom_id,
                headline=headline_text,
                status=todo_state,
                section=section_name,
                content=heading_to_org_string(heading),
                id=task_id,
                created=created,
                modified=modified,
                closed=closed,
            )
        )

    return tasks


###############################################################################
#
def find_task(
    identifier: str, section: str | None = None
) -> tuple[Task, Heading, Heading, Org]:
    """
    Find a task by identifier.

    Args:
        identifier: Task :CUSTOM_ID:, ticket ID (e.g., GH-28), or headline substring
        section: Section to search in (searches all sections if None)

    Returns:
        Tuple of (Task, heading, section_heading, org)

    Raises:
        ValueError: If task is not found

    Note:
        Matches in order: exact :CUSTOM_ID:, :CUSTOM_ID: with "task-" prefix,
        ticket ID in headline, or substring in headline.
    """
    org = get_org()
    sections = [section] if section else [ACTIVE_SECTION, COMPLETED_SECTION]

    for sec_name in sections:
        section_heading = find_section(org, sec_name)
        if not section_heading:
            continue

        for heading in section_heading.children:
            if heading.headline.level != 2:
                continue

            todo_state = heading.headline.todo
            if todo_state not in ALL_STATES:
                continue

            # Get properties from the :PROPERTIES: drawer
            properties = _properties(heading)

            headline_text = (
                heading.headline.title
                if hasattr(heading.headline, "title")
                else str(heading.headline)
            )

            # Check if the identifer.lower().strip() is in either the CUSTOM_ID
            # or the headline text, then we have a match.
            #
            if properties.CUSTOM_ID == identifier:
                matches = True
            elif properties.CUSTOM_ID == f"task-{identifier.strip().lower()}":
                matches = True
            elif identifier.strip().lower() in headline_text.lower():
                matches = True
            else:
                matches = False

            if matches:
                task = Task(
                    custom_id=properties.CUSTOM_ID,
                    headline=headline_text,
                    status=todo_state,
                    section=sec_name,
                    content=heading_to_org_string(heading),
                    id=properties.ID,
                    created=properties.CREATED,
                    modified=properties.MODIFIED,
                    closed=properties.CLOSED,
                )
                result = (task, heading, section_heading, org)
                return result

    raise ValueError(
        f"Could not find task '{identifier}' in section '{section}'"
    )


###############################################################################
#
def list_tasks(section_name: str) -> list[Task]:
    """
    List all tasks in a section.

    Args:
        section_name: Name of the section to list tasks from

    Returns:
        List of all tasks in the specified section
    """
    org = get_org()
    section_heading = find_section(org, section_name)
    return parse_tasks_in_section(section_heading, section_name)


###############################################################################
#
def parse_task_entry(task_entry: str) -> Heading:
    """
    Parse a task entry string into a Heading object.

    Args:
        task_entry: Org-mode formatted task entry (level 2 heading)

    Returns:
        Parsed Heading object

    Raises:
        ValueError: If task_entry does not contain a level 2 heading

    Note:
        Wraps task in a dummy level 1 section for parsing since orgmunge
        requires org content to start with a level 1 heading.
    """
    # Wrap in a dummy level-1 section so orgmunge can parse it
    wrapped = f"* _temp_section_\n{task_entry}\n"
    temp_org = Org(wrapped, from_file=False)

    # Get the dummy section and extract its first child (the task)
    temp_section = list(temp_org.root.children)[0]
    task_headings = [h for h in temp_section.children if h.headline.level == 2]

    if not task_headings:
        raise ValueError(
            "task_entry must contain a level-2 heading (** TODO ...)"
        )

    return task_headings[0]


# =============================================================================
# High Level Tasks Checklist Management
# =============================================================================


###############################################################################
#
def extract_task_description(headline_text: str) -> str:
    """
    Extract task description from headline, removing TODO/DONE and ticket ID.

    Args:
        headline_text: Full task headline text

    Returns:
        Clean description without status or ticket ID

    Examples:
        "TODO GH-178 Add multi-provider support" -> "Add multi-provider support"
        "DONE Fix authentication bug" -> "Fix authentication bug"
        "TODO JIRA-1234 Migrate rules" -> "Migrate rules"
    """
    # Remove TODO/DONE prefix
    text = headline_text
    for prefix in ["TODO ", "DONE "]:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break

    # Remove ticket ID prefix (e.g., "GH-123 ", "JIRA-456 ")
    ticket_pattern = r"^([A-Z]+-\d+)\s+"
    text = re.sub(ticket_pattern, "", text)

    return text.strip()


###############################################################################
#
def add_high_level_task(org: Org, description: str) -> None:
    """
    Add a new unchecked item to the High Level Tasks checklist.

    Args:
        org: The Org object to modify
        description: Task description for the checklist item

    Note:
        Does nothing if High Level Tasks section does not exist.
    """
    high_level_section = find_section(org, HIGH_LEVEL_SECTION)
    if high_level_section is None:
        # If High Level Tasks section doesn't exist, skip
        return

    # Get the body content
    body = high_level_section.body or ""

    # Add new checkbox item at the end
    checkbox_line = f"- [ ] {description}"
    if body.strip():
        # Append to existing body
        body = body.rstrip() + "\n" + checkbox_line + "\n"
    else:
        # First item
        body = checkbox_line + "\n"

    high_level_section.body = body


###############################################################################
#
def update_high_level_task(org: Org, description: str, completed: bool) -> None:
    """
    Update an existing checklist item's completion status.

    Args:
        org: The Org object to modify
        description: Task description to find in the checklist
        completed: True to mark as [X], False to mark as [ ]

    Note:
        Does nothing if High Level Tasks section does not exist.
    """
    high_level_section = find_section(org, HIGH_LEVEL_SECTION)
    if high_level_section is None:
        return

    body = high_level_section.body or ""
    lines = body.split("\n")

    # Find and update the matching checkbox
    marker = "[X]" if completed else "[ ]"
    opposite_marker = "[ ]" if completed else "[X]"

    for i, line in enumerate(lines):
        # Check if this line is a checkbox with our description
        if (
            f"- {opposite_marker} {description}" in line
            or f"- {marker} {description}" in line
        ):
            # Update the marker
            lines[i] = f"- {marker} {description}"
            break

    high_level_section.body = "\n".join(lines)


###############################################################################
#
def create_task(section_name: str, task_entry: str) -> tuple[str, str]:
    """
    Add a new task to the specified section.

    Args:
        section_name: Section to add the task to
        task_entry: Complete org-formatted task entry string

    Returns:
        Tuple of (section_name, task_content)

    Raises:
        ValueError: If section is not found

    Note:
        Automatically generates UUID for :ID: property if not present.
        Sets :CREATED: timestamp when creating new task.
        Adds to High Level Tasks checklist if creating in active section.
    """
    org = get_org()

    # Parse the new task entry
    new_task = parse_task_entry(task_entry)
    target_section = find_section(org, section_name)

    if target_section is None:
        raise ValueError(f"Section not found: {section_name}")

    # Generate UUID for :ID: property if not present
    if not hasattr(new_task, "properties") or not new_task.properties:
        new_task.properties = {}
    if "ID" not in new_task.properties:
        new_task.properties["ID"] = str(uuid.uuid4()).upper()

    # Set :CREATED: timestamp (active) when creating new task
    if "CREATED" not in new_task.properties:
        new_task.properties["CREATED"] = get_current_timestamp(active=True)

    target_section.add_child(new_task, new=True)

    # Add to High Level Tasks checklist if creating in active section
    if section_name == ACTIVE_SECTION:
        headline_title = (
            new_task.headline.title
            if hasattr(new_task.headline, "title")
            else str(new_task.headline)
        )
        description = extract_task_description(headline_title)
        add_high_level_task(org, description)

    org.write(str(TASKS_FILE))

    # Return section and the task content for formatting
    return (section_name, heading_to_org_string(new_task))


###############################################################################
#
def update_task(
    identifier: str, new_task_entry: str
) -> tuple[Task, str, bool, str, str]:
    """
    Replace a task with new content, moving sections if status changed.

    Args:
        identifier: String to find the task (CUSTOM_ID, ticket ID, or headline)
        new_task_entry: Complete org-mode task entry as a string

    Returns:
        Tuple of (old_task, new_content, was_moved, old_section, new_section)

    Note:
        Automatically sets :MODIFIED: timestamp to current time.
        Sets :CLOSED: timestamp when transitioning TODO -> DONE.
        Removes :CLOSED: timestamp when transitioning DONE -> TODO.
        Moves task between sections based on status (TODO/DONE).
        Updates High Level Tasks checklist when status changes.
    """
    task, old_heading, old_section_heading, org = find_task(identifier)

    old_section_name = task.section
    old_status = task.status

    # Parse the new task we got as a string into an orgmung Heading object
    #
    new_task = parse_task_entry(new_task_entry)
    new_status = new_task.headline.todo

    # Set the timestamp properties. `:MODIFIED:` always gets set to the current
    # time. `:CLOSED:` gets set if this task is transitioning from "TODO" to
    # "DONE"
    #
    new_task.properties["MODIFIED"] = get_current_timestamp(active=False)

    if task.created and "CREATED" not in new_task.properties:
        new_task.properties["CREATED"] = task.created
    if task.closed and "CLOSED" not in new_task.properties:
        new_task.properties["CLOSED"] = task.closed

    # TODO -> DONE: set :CLOSED:
    # DONE -> TODO: remove :CLOSED:
    # any other transition, :CLOSED: is not modified.
    #
    if old_status == "TODO":
        if new_task.headline.todo == "DONE":
            # Task has moved from TODO -> DONE, set :CLOSED:
            #
            new_task.properties["CLOSED"] = get_current_timestamp(active=True)
    else:  # task.headline.todo == "DONE"
        if new_task.headline.todo == "TODO":
            # The task has moved from "DONE" to "TODO". Remove :CLOSED: if it
            # is set
            #
            del new_task.properties["CLOSED"]

    # Determine target section based on new status
    if new_status == "DONE":
        target_section = find_section(org, COMPLETED_SECTION)
        target_section_name = COMPLETED_SECTION
    else:
        target_section = find_section(org, ACTIVE_SECTION)
        target_section_name = ACTIVE_SECTION

    if target_section is None:
        raise ValueError(f"Target section not found for status: {new_status}")

    # If staying in same section, preserve position
    if old_section_heading == target_section:
        children = list(old_section_heading.children)
        try:
            idx = children.index(old_heading)
        except ValueError as e:
            raise ValueError("Could not find task heading in section") from e

        old_section_heading.remove_child(old_heading)
        target_section.add_child(new_task, new=True)

        # Reorder to preserve position
        current_children = list(target_section.children)
        if len(current_children) > 1:
            new_task_in_list = current_children[-1]
            current_children.pop()
            current_children.insert(idx, new_task_in_list)
            target_section.children = current_children
    else:
        # Moving to different section
        old_section_heading.remove_child(old_heading)
        target_section.add_child(new_task, new=True)

    # Update High Level Tasks checklist if status changed
    if was_moved := (old_section_name != target_section_name):
        headline_title = (
            new_task.headline.title
            if hasattr(new_task.headline, "title")
            else str(new_task.headline)
        )
        description = extract_task_description(headline_title)
        if new_status == "DONE":
            # Mark as completed in checklist
            update_high_level_task(org, description, completed=True)
        else:
            # Mark as incomplete in checklist
            update_high_level_task(org, description, completed=False)

    org.write(str(TASKS_FILE))

    new_content = heading_to_org_string(new_task)

    return (task, new_content, was_moved, old_section_name, target_section_name)


###############################################################################
#
def move_task(
    identifier: str, from_section: str, to_section: str
) -> tuple[str, str, str]:
    """
    Move a task from one section to another.

    Args:
        identifier: String to find the task
        from_section: Source section name
        to_section: Destination section name

    Returns:
        Tuple of (headline, from_section, to_section)

    Raises:
        ValueError: If task not found or target section not found
    """
    result = find_task(identifier, from_section)
    task, heading, old_section, org = result
    target_section = find_section(org, to_section)

    if target_section is None:
        raise ValueError(f"Target section not found: {to_section}")

    old_section.remove_child(heading)
    target_section.add_child(heading, new=True)
    org.write(str(TASKS_FILE))

    return (task.headline, from_section, to_section)


###############################################################################
#
def search_tasks(query: str) -> list[Task]:
    """
    Search tasks across all sections.

    Args:
        query: Search query string (case-insensitive)

    Returns:
        List of tasks matching the query in headline or content
    """
    all_tasks = []
    all_tasks.extend(list_tasks(ACTIVE_SECTION))
    all_tasks.extend(list_tasks(COMPLETED_SECTION))

    query_lower = query.lower()
    return [
        t
        for t in all_tasks
        if query_lower in t.headline.lower() or query_lower in t.content.lower()
    ]


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
    if not JOURNAL_DIR.exists():
        return ""
    # Check if any YYYYMMDD.org files exist
    for path in JOURNAL_DIR.iterdir():
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
    base_path = JOURNAL_DIR / target_date.strftime("%Y%m%d")

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
def write_file(path: Path, content: str) -> None:
    """
    Write content to file, ensuring it ends with newline.

    Args:
        path: Path to write to
        content: Content to write

    Note:
        Creates parent directories if they don't exist.
        Automatically adds trailing newline if not present.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


###############################################################################
#
def backup_file(path: Path) -> Path:
    """
    Create a timestamped backup before modifications.

    Args:
        path: Path to the file to backup

    Returns:
        Path to the backup file (original path with timestamp suffix)

    Note:
        Does nothing if file doesn't exist (returns original path).
        Backup format: original.YYYYMMDD_HHMMSS.bak
    """
    if not path.exists():
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".{timestamp}.bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


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

    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8").rstrip()
        new_content = f"{existing}\n\n{entry_text}"
    else:
        date_heading = target_date.strftime("* %Y-%m-%d")
        new_content = f"{date_heading}\n\n{entry_text}"

    backup_file(file_path)
    write_file(file_path, new_content)

    return (target_date, entry)


###############################################################################
#
def update_journal_entry(
    file_path: Path,
    line_number: int,
    time_str: str,
    headline: str,
    content: str,
    tags: list[str] | None = None,
) -> tuple[JournalEntry, JournalEntry, date]:
    """
    Update an existing journal entry by line number.

    Args:
        file_path: Path to the journal file
        line_number: Line number where entry starts
        time_str: New time in HH:MM format
        headline: New headline text
        content: New body content
        tags: Optional new tags list

    Returns:
        Tuple of (old_entry, new_entry, date)

    Note:
        Creates backup before modification.
        Replaces entry while preserving other entries.
    """
    file_content = file_path.read_text(encoding="utf-8")
    lines = file_content.split("\n")

    # Parse existing entry to get old content
    old_entry, _ = parse_journal_entry(lines, line_number, file_path.name)

    entry_start = line_number
    entry_end = entry_start + 1

    while entry_end < len(lines):
        if lines[entry_end].startswith("** ") or lines[entry_end].startswith(
            "* "
        ):
            break
        entry_end += 1

    tags = tags or []
    new_entry = JournalEntry(
        time=time_str,
        headline=headline,
        tags=tags,
        content=content,
        line_number=line_number,
        file_date=file_path.name,
    )

    new_entry_lines = new_entry.to_org().split("\n")
    new_lines = lines[:entry_start] + new_entry_lines + lines[entry_end:]

    backup_file(file_path)
    write_file(file_path, "\n".join(new_lines))

    # Parse date from filename (YYYYMMDD or YYYYMMDD.org)
    date_str = file_path.stem if file_path.suffix == ".org" else file_path.name
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
# Serialization Helpers
# =============================================================================


###############################################################################
#
def task_to_dict(task: Task) -> dict:
    """
    Convert task to dictionary for JSON output.

    Args:
        task: Task object to convert

    Returns:
        Dictionary with task fields suitable for JSON serialization
    """
    return {
        "name": task.custom_id,
        "headline": task.headline,
        "status": task.status,
        "section": task.section,
        "ticket_id": task.ticket_id,
        "content": task.content,
    }


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


# =============================================================================
# MCP Tool Definitions
# =============================================================================


###############################################################################
#
@server.list_tools()
async def list_tools():
    return [
        # ----- Task Tools -----
        Tool(
            name="list_tasks",
            description="List all tasks in a section of tasks.org. Returns task names, headlines, status, and full content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section name",
                        "enum": [ACTIVE_SECTION, COMPLETED_SECTION],
                    }
                },
                "required": ["section"],
            },
        ),
        Tool(
            name="get_task",
            description="Get a specific task by identifier (#+NAME like 'task-gh-28', ticket ID like 'GH-28', or headline substring). Returns full task content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Task identifier: #+NAME value, JIRA ticket ID, or headline substring",
                    },
                    "section": {
                        "type": "string",
                        "description": "Section to search (optional, searches all if omitted)",
                        "enum": [ACTIVE_SECTION, COMPLETED_SECTION],
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="create_task",
            description="Create a new task in a section. Provide the complete org-formatted task entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section to add the task to",
                        "enum": [ACTIVE_SECTION, COMPLETED_SECTION],
                    },
                    "task_entry": {
                        "type": "string",
                        "description": "Complete task in org format: '** TODO headline\\n#+NAME: task-id\\n*** Task items [/]\\n- [ ] item'",
                    },
                },
                "required": ["section", "task_entry"],
            },
        ),
        Tool(
            name="update_task",
            description="Update an existing task. Provide complete new task entry. Task will be moved to appropriate section if status changes (TODO->DONE moves to Completed).",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Task identifier to find the task",
                    },
                    "task_entry": {
                        "type": "string",
                        "description": "Complete new task in org format",
                    },
                },
                "required": ["identifier", "task_entry"],
            },
        ),
        Tool(
            name="preview_task_update",
            description="Preview changes to a task WITHOUT modifying the file. Shows diff of what would change. Use this before update_task to verify changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Task identifier to find the task",
                    },
                    "task_entry": {
                        "type": "string",
                        "description": "Complete new task in org format (to compare against current)",
                    },
                },
                "required": ["identifier", "task_entry"],
            },
        ),
        Tool(
            name="move_task",
            description="Move a task between sections (e.g., Active to Completed) without modifying content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Task identifier (#+NAME, ticket ID, or headline)",
                    },
                    "from_section": {
                        "type": "string",
                        "enum": [ACTIVE_SECTION, COMPLETED_SECTION],
                    },
                    "to_section": {
                        "type": "string",
                        "enum": [ACTIVE_SECTION, COMPLETED_SECTION],
                    },
                },
                "required": ["identifier", "from_section", "to_section"],
            },
        ),
        Tool(
            name="search_tasks",
            description="Search tasks by query string across all sections. Returns complete matching tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (matches headline and content)",
                    }
                },
                "required": ["query"],
            },
        ),
        # ----- Journal Tools -----
        Tool(
            name="list_journal_entries",
            description="List all journal entries for a specific date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format. Defaults to today.",
                    }
                },
            },
        ),
        Tool(
            name="get_journal_entry",
            description="Get a specific journal entry by date and time or headline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format",
                    },
                    "identifier": {
                        "type": "string",
                        "description": "Time (HH:MM) or headline substring to find the entry",
                    },
                },
                "required": ["date", "identifier"],
            },
        ),
        Tool(
            name="create_journal_entry",
            description="Create a new journal entry. Format: ** HH:MM headline :tags:",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format. Defaults to today.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM format. Defaults to current time.",
                    },
                    "headline": {
                        "type": "string",
                        "description": "Entry headline (e.g., 'GH-28 [[url][#28]] Completed migration')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Entry body (bullet points with details)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags like 'daily_summary'",
                    },
                },
                "required": ["headline", "content"],
            },
        ),
        Tool(
            name="update_journal_entry",
            description="Update an existing journal entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format",
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "Line number of entry to update (from list_journal_entries)",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM format",
                    },
                    "headline": {
                        "type": "string",
                        "description": "New headline",
                    },
                    "content": {
                        "type": "string",
                        "description": "New body content",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated tags (replaces existing)",
                    },
                },
                "required": [
                    "date",
                    "line_number",
                    "time",
                    "headline",
                    "content",
                ],
            },
        ),
        Tool(
            name="preview_journal_update",
            description="Preview changes to a journal entry WITHOUT modifying the file. Shows diff of what would change. Use this before update_journal_entry to verify changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format",
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "Line number of entry to preview (from list_journal_entries)",
                    },
                    "time": {
                        "type": "string",
                        "description": "New time in HH:MM format",
                    },
                    "headline": {
                        "type": "string",
                        "description": "New headline",
                    },
                    "content": {
                        "type": "string",
                        "description": "New body content",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags",
                    },
                },
                "required": [
                    "date",
                    "line_number",
                    "time",
                    "headline",
                    "content",
                ],
            },
        ),
        Tool(
            name="search_journal",
            description="Search journal entries by query. Returns complete matching entries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "days_back": {
                        "type": "integer",
                        "description": "Days to search back (default 30)",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


# =============================================================================
# MCP Tool Handlers
# =============================================================================


###############################################################################
#
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        match name:
            # ----- Task Operations -----
            case "list_tasks":
                tasks = list_tasks(arguments["section"])
                output = format_task_list(tasks, arguments["section"])
                return [TextContent(type="text", text=output)]

            case "get_task":
                try:
                    found = find_task(
                        arguments["identifier"], arguments.get("section")
                    )
                except ValueError:
                    return [
                        TextContent(
                            type="text",
                            text=f"Task '{arguments['identifier']}' not found",
                        )
                    ]
                task, _, _, _ = found
                output = format_task_detail(task)
                return [TextContent(type="text", text=output)]

            case "create_task":
                section, task_content = create_task(
                    arguments["section"], arguments["task_entry"]
                )
                output = format_task_create_result(section, task_content)
                return [TextContent(type="text", text=output)]

            case "update_task":
                old_task, new_content, moved, old_section, new_section = (
                    update_task(
                        arguments["identifier"], arguments["task_entry"]
                    )
                )
                output = format_task_update_result(
                    old_task, new_content, moved, old_section, new_section
                )
                return [TextContent(type="text", text=output)]

            case "preview_task_update":
                try:
                    result = find_task(arguments["identifier"])
                except ValueError:
                    return [
                        TextContent(
                            type="text",
                            text=f"Task '{arguments['identifier']}' not found",
                        )
                    ]
                task, _, _, _ = result
                new_heading = parse_task_entry(arguments["task_entry"])
                new_content = heading_to_org_string(new_heading)
                new_status = new_heading.headline.todo
                new_section = (
                    COMPLETED_SECTION
                    if new_status == "DONE"
                    else ACTIVE_SECTION
                )
                output = format_task_preview(
                    task, new_content, task.section, new_section
                )
                return [TextContent(type="text", text=output)]

            case "move_task":
                headline, from_section, to_section = move_task(
                    arguments["identifier"],
                    arguments["from_section"],
                    arguments["to_section"],
                )
                output = format_move_result(headline, from_section, to_section)
                return [TextContent(type="text", text=output)]

            case "search_tasks":
                tasks = search_tasks(arguments["query"])
                output = format_search_results(tasks, "task")
                return [TextContent(type="text", text=output)]

            # ----- Journal Operations -----
            case "list_journal_entries":
                date_str = arguments.get("date", date.today().isoformat())
                target_date = date.fromisoformat(date_str)
                entries = parse_journal_entries(get_journal_path(target_date))
                output = format_journal_list(entries, date_str)
                return [TextContent(type="text", text=output)]

            case "get_journal_entry":
                target_date = date.fromisoformat(arguments["date"])
                entries = parse_journal_entries(get_journal_path(target_date))
                entry_id = arguments["identifier"]
                for e in entries:
                    if (
                        e.time == entry_id
                        or entry_id.lower() in e.headline.lower()
                    ):
                        output = format_journal_detail(e)
                        return [TextContent(type="text", text=output)]
                return [
                    TextContent(
                        type="text", text=f"Entry '{entry_id}' not found"
                    )
                ]

            case "create_journal_entry":
                target_date = date.fromisoformat(
                    arguments.get("date", date.today().isoformat())
                )
                time_str = arguments.get(
                    "time", datetime.now().strftime("%H:%M")
                )
                result_date, entry = create_journal_entry(
                    target_date,
                    time_str,
                    arguments["headline"],
                    arguments["content"],
                    arguments.get("tags", []),
                )
                output = format_journal_create_result(result_date, entry)
                return [TextContent(type="text", text=output)]

            case "update_journal_entry":
                target_date = date.fromisoformat(arguments["date"])
                old_entry, new_entry, result_date = update_journal_entry(
                    get_journal_path(target_date),
                    arguments["line_number"],
                    arguments["time"],
                    arguments["headline"],
                    arguments["content"],
                    arguments.get("tags"),
                )
                output = format_journal_update_result(
                    old_entry, new_entry, result_date
                )
                return [TextContent(type="text", text=output)]

            case "preview_journal_update":
                target_date = date.fromisoformat(arguments["date"])
                file_path = get_journal_path(target_date)
                entries = parse_journal_entries(file_path)

                # Find entry by line number
                existing_entry: JournalEntry | None = None
                for entry in entries:
                    if entry.line_number == arguments["line_number"]:
                        existing_entry = entry
                        break

                if existing_entry is None:
                    return [
                        TextContent(
                            type="text",
                            text=f"Entry at line {arguments['line_number']} not found",
                        )
                    ]

                # Create new entry object for comparison
                proposed_entry = JournalEntry(
                    time=arguments["time"],
                    headline=arguments["headline"],
                    tags=arguments.get("tags", []),
                    content=arguments["content"],
                    line_number=arguments["line_number"],
                    file_date=file_path.name,
                )
                output = format_journal_preview(existing_entry, proposed_entry)
                return [TextContent(type="text", text=output)]

            case "search_journal":
                entries = search_journal(
                    arguments["query"], arguments.get("days_back", 30)
                )
                output = format_search_results(entries, "journal entry")
                return [TextContent(type="text", text=output)]

            case _:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except FileNotFoundError as e:
        return [TextContent(type="text", text=f"File not found: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        return [
            TextContent(
                type="text", text=f"Unexpected error: {type(e).__name__}: {e}"
            )
        ]


# =============================================================================
# Resources
# =============================================================================


###############################################################################
#
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="org://tasks/active",
            name="Active Tasks",
            description="Tasks in the Active Task List",
        ),
        Resource(
            uri="org://tasks/completed",
            name="Completed Tasks",
            description="Tasks in the Completed Task List",
        ),
        Resource(
            uri="org://journal/today",
            name="Today's Journal",
            description="Journal entries for today",
        ),
    ]


###############################################################################
#
@server.read_resource()
async def read_resource(uri: str):
    match uri:
        case "org://tasks/active":
            tasks = list_tasks(ACTIVE_SECTION)
            return json.dumps([task_to_dict(t) for t in tasks], indent=2)
        case "org://tasks/completed":
            tasks = list_tasks(COMPLETED_SECTION)
            return json.dumps([task_to_dict(t) for t in tasks], indent=2)
        case "org://journal/today":
            entries = parse_journal_entries(get_journal_path(date.today()))
            return json.dumps(
                [journal_entry_to_dict(e) for e in entries], indent=2
            )
        case _:
            raise ValueError(f"Unknown resource: {uri}")


# =============================================================================
# Main
# =============================================================================


###############################################################################
#
async def main():
    init_options = InitializationOptions(
        server_name="emacs-org-mode",
        server_version="0.1.0",
        capabilities=ServerCapabilities(
            tools={},
            resources={},
        ),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


###############################################################################
###############################################################################
#
if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
