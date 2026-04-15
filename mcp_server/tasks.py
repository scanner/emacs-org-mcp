"""
Task operations: data structure, orgmunge operations, CRUD, and formatting.
"""

# system imports
import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

# 3rd party imports
from orgmunge import Org
from orgmunge.classes import Heading

# project imports
from mcp_server.config import global_state
from mcp_server.utils import (
    format_simple_diff,
    get_current_timestamp,
    request_ediff_approval,
)

# =============================================================================
# Constants
# =============================================================================

# These are the properties we care about on a task in tasks.org
PROPERTIES = ("CUSTOM_ID", "ID", "CREATED", "MODIFIED", "CLOSED")

# TODO/DONE states from orgmunge
TODO_STATES = (v for k, v in Org.get_todos()["todo_states"].items())
DONE_STATES = (v for k, v in Org.get_todos()["done_states"].items())
ALL_STATES = tuple(list(TODO_STATES) + list(DONE_STATES))


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
    tasks_file = global_state.config.tasks_file
    if not tasks_file.exists():
        raise FileNotFoundError(f"Tasks file not found: {tasks_file}")
    return Org(str(tasks_file))


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
# Canonical property order for the :PROPERTIES: drawer.  Known properties are
# written first in this order; any unrecognised extras follow alphabetically.
_PROPERTY_ORDER = (
    "ID",
    "CUSTOM_ID",
    "CREATED",
    "MODIFIED",
    "CLOSED",
    "PROJECT",
)


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
        Renders the :PROPERTIES: drawer when properties are present so that
        callers (e.g. get_task) see the full task including CUSTOM_ID / ID /
        PROJECT etc. and can round-trip them through update_task without loss.
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

    # Render :PROPERTIES: drawer immediately after the headline
    props: dict = (
        heading.properties
        if hasattr(heading, "properties") and heading.properties
        else {}
    )
    if props:
        lines.append(":PROPERTIES:")
        rendered: set[str] = set()
        for prop in _PROPERTY_ORDER:
            if prop in props:
                lines.append(f"   :{prop}: {props[prop]}")
                rendered.add(prop)
        for prop in sorted(props.keys()):
            if prop not in rendered:
                lines.append(f"   :{prop}: {props[prop]}")
        lines.append(":END:")

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
    sections = (
        [section]
        if section
        else [
            global_state.config.active_section,
            global_state.config.completed_section,
        ]
    )

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

            # Check if the identifer.lower().strip() is in either the
            # CUSTOM_ID or the headline text, then we have a match.
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
    high_level_section = find_section(
        org, global_state.config.high_level_section
    )
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
    high_level_section = find_section(
        org, global_state.config.high_level_section
    )
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


# =============================================================================
# Task CRUD Operations
# =============================================================================


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

    # Generate org string for the new task
    new_task_org = heading_to_org_string(new_task)

    # Get context name from task (custom_id or fallback)
    custom_id = new_task.properties.get("CUSTOM_ID", "new-task")
    context_name = custom_id.lstrip("task-")  # e.g., "gh-127" or "new-task"

    # Request approval via ediff
    approved, final_content = request_ediff_approval(
        old_content="",  # Empty for create
        new_content=new_task_org,
        context_name=context_name,
    )

    if not approved:
        raise ValueError("User rejected task creation")

    # If edited, re-parse the final content and re-apply automatic properties
    if final_content != new_task_org:
        new_task = parse_task_entry(final_content)
        # Re-apply automatic properties
        if not hasattr(new_task, "properties") or not new_task.properties:
            new_task.properties = {}
        if "ID" not in new_task.properties:
            new_task.properties["ID"] = str(uuid.uuid4()).upper()
        if "CREATED" not in new_task.properties:
            new_task.properties["CREATED"] = get_current_timestamp(active=True)

    target_section.add_child(new_task, new=True)

    # Add to High Level Tasks checklist if creating in active section
    if section_name == global_state.config.active_section:
        headline_title = (
            new_task.headline.title
            if hasattr(new_task.headline, "title")
            else str(new_task.headline)
        )
        description = extract_task_description(headline_title)
        add_high_level_task(org, description)

    org.write(str(global_state.config.tasks_file))

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

    # Set the timestamp properties. `:MODIFIED:` always gets set to the
    # current time. `:CLOSED:` gets set if this task is transitioning
    # from "TODO" to "DONE"
    #
    new_task.properties["MODIFIED"] = get_current_timestamp(active=False)

    # Preserve all properties from the old task that the incoming entry omitted.
    # This covers :ID:, :CUSTOM_ID:, :CREATED:, :PROJECT:, and any future
    # custom properties.  :MODIFIED: and :CLOSED: are excluded here because
    # they are managed explicitly below.
    auto_managed = {"MODIFIED", "CLOSED"}
    for prop, val in old_heading.properties.items():
        if prop not in auto_managed and prop not in new_task.properties:
            new_task.properties[prop] = val

    # Handle CLOSED property based on status transitions
    # TODO -> DONE: set :CLOSED:
    # DONE -> TODO: remove :CLOSED:
    # DONE -> DONE: preserve existing :CLOSED:
    #
    if old_status == "TODO":
        if new_task.headline.todo == "DONE":
            # Task has moved from TODO -> DONE, set :CLOSED:
            new_task.properties["CLOSED"] = get_current_timestamp(active=True)
    elif old_status == "DONE":
        if new_task.headline.todo == "TODO":
            # The task has moved from "DONE" to "TODO". Remove :CLOSED:
            if "CLOSED" in new_task.properties:
                del new_task.properties["CLOSED"]
        else:
            # DONE -> DONE: preserve existing CLOSED if not in new properties
            if task.closed and "CLOSED" not in new_task.properties:
                new_task.properties["CLOSED"] = task.closed

    # Get old task org string for approval
    old_task_org = heading_to_org_string(old_heading)
    new_task_org = heading_to_org_string(new_task)

    # Get context name from old task (should have custom_id)
    custom_id = task.custom_id or "unknown-task"
    context_name = custom_id.lstrip("task-")  # e.g., "gh-127"

    # Request approval via ediff
    approved, final_content = request_ediff_approval(
        old_content=old_task_org,
        new_content=new_task_org,
        context_name=context_name,
    )

    if not approved:
        raise ValueError("User rejected task update")

    # If edited, re-parse and re-apply automatic properties
    if final_content != new_task_org:
        new_task = parse_task_entry(final_content)
        new_status = new_task.headline.todo
        # Re-apply automatic properties
        new_task.properties["MODIFIED"] = get_current_timestamp(active=False)
        for prop, val in old_heading.properties.items():
            if prop not in auto_managed and prop not in new_task.properties:
                new_task.properties[prop] = val

        # Handle CLOSED property based on status transitions
        if old_status == "TODO" and new_status == "DONE":
            # TODO -> DONE: set CLOSED
            new_task.properties["CLOSED"] = get_current_timestamp(active=True)
        elif old_status == "DONE" and new_status == "TODO":
            # DONE -> TODO: remove CLOSED
            if "CLOSED" in new_task.properties:
                del new_task.properties["CLOSED"]
        elif old_status == "DONE" and new_status == "DONE":
            # DONE -> DONE: preserve existing CLOSED
            if task.closed and "CLOSED" not in new_task.properties:
                new_task.properties["CLOSED"] = task.closed

    # Determine target section based on new status
    if new_status == "DONE":
        target_section = find_section(
            org, global_state.config.completed_section
        )
        target_section_name = global_state.config.completed_section
    else:
        target_section = find_section(org, global_state.config.active_section)
        target_section_name = global_state.config.active_section

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

    org.write(str(global_state.config.tasks_file))

    new_content = heading_to_org_string(new_task)

    return (
        task,
        new_content,
        was_moved,
        old_section_name,
        target_section_name,
    )


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
    org.write(str(global_state.config.tasks_file))

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
    all_tasks.extend(list_tasks(global_state.config.active_section))
    all_tasks.extend(list_tasks(global_state.config.completed_section))

    query_lower = query.lower()
    return [
        t
        for t in all_tasks
        if query_lower in t.headline.lower() or query_lower in t.content.lower()
    ]


# =============================================================================
# Task Formatting
# =============================================================================


###############################################################################
#
def format_task_update_result(
    old_task: Task,
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
def format_task_list(tasks: list[Task], section: str) -> str:
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
def format_task_detail(task: Task) -> str:
    """
    Format a single task in full detail.

    Args:
        task: The task to format

    Returns:
        Formatted task with all metadata and complete content
    """
    ticket = f"[{task.ticket_id}] " if task.ticket_id else ""

    lines = [
        f"{task.status}  {ticket}{task.headline}",
        f"Section: {task.section}",
        "",
        task.content,
    ]
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
