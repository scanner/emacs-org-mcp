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
from mcp_server.properties import format_drawer
from mcp_server.results import (
    DetailLevel,
    Record,
    render,
)
from mcp_server.utils import (
    format_age,
    format_simple_diff,
    get_current_timestamp,
    request_ediff_approval,
    write_file,
)
from mcp_server.validation import (
    HEADING_RE,
    find_indented_headings,
    scan_headings,
    validate_task_entry,
)

# =============================================================================
# Constants
# =============================================================================

# These are the properties we care about on a task in tasks.org
PROPERTIES = ("CUSTOM_ID", "ID", "CREATED", "MODIFIED", "CLOSED")

# A trailing progress cookie on a section heading, e.g. the "[1/2]" in
# "* High Level Tasks (in order) [1/2]".  Stripped when comparing sections
# across a write, since the cookie changes while the section does not.
SECTION_COOKIE_RE = re.compile(r"[ \t]*\[\d*/\d*\][ \t]*$")

# Where a task may be placed in its section. Position is priority, so these
# are the vocabulary for saying what a task's priority is relative to the rest.
# Deliberately not integer indices: an index shifts every time anything moves,
# so a caller would have to compute a fresh one for every call.
POSITIONS = ("top", "bottom", "before", "after")

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

    # A headline is "STARS TODO [#PRIORITY] title [cookie] :tags:", and
    # orgmunge parses the priority and the progress cookie out of the title
    # into their own attributes. Rebuilding from the title alone therefore
    # drops both, which deletes them from the file on the next write --
    # get_task would hand back a task whose cookies had already gone, and
    # writing that straight back is what erodes a task over successive edits.
    # Both attributes arrive already bracketed, so they only need placing.
    #
    # NOTE: neither is a plain string. An absent priority is an object that is
    #       still truthy and only renders empty, so the test has to be on the
    #       rendered text rather than on the attribute.
    #
    priority = str(heading.headline.priority or "")
    priority_str = f"{priority} " if priority else ""
    cookie = str(heading.headline.cookie or "")
    cookie_str = f" {cookie}" if cookie else ""

    lines.append(f"{stars} {todo}{priority_str}{title}{cookie_str}{tags_str}")

    # Render :PROPERTIES: drawer immediately after the headline
    props: dict = (
        heading.properties
        if hasattr(heading, "properties") and heading.properties
        else {}
    )
    lines.extend(format_drawer(props))

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


# =============================================================================
# Destructive-Write Guard
# =============================================================================


###############################################################################
#
# Trailing org tags on a headline, e.g. "  :booklore:work:".
_TAGS_RE = re.compile(r"[ \t]+(:[\w@%#]+)+:[ \t]*$")


###############################################################################
#
def _strip_tags(headline: str) -> str:
    """
    Remove trailing org tags from a headline.

    Args:
        headline: Headline text, possibly ending in ``:tag1:tag2:``

    Returns:
        The headline without its tags.

    Note:
        The parser reports ``headline.title`` with tags already stripped, so a
        raw scan has to strip them too.  Otherwise a task carrying tags and no
        :CUSTOM_ID: never matches its parsed counterpart, and the write guard
        refuses perfectly good writes.
    """
    return _TAGS_RE.sub("", headline).strip()


###############################################################################
#
def scan_task_identities(file_content: str) -> list[str]:
    """
    List every task in a tasks.org file by scanning the raw text.

    Args:
        file_content: Full text of a tasks.org file

    Returns:
        Identities in file order.  A task is identified by its ``:CUSTOM_ID:``
        when it has one, otherwise by ``headline:<text>``.

    Note:
        This deliberately does NOT go through orgmunge.  It is the ground truth
        the parser is checked against: any level-2 heading carrying a TODO/DONE
        keyword is a task, wherever it sits in the tree.  That is what makes it
        able to notice tasks the parser has lost track of.

        Indented headings are counted too.  Org treats " ** TODO Task" as body
        text and folds it into the preceding task, but it is unmistakably a
        task the user still has, so it must be protected from deletion like any
        other.
    """
    lines = file_content.split("\n")
    identities: list[str] = []

    found = scan_headings(file_content) + find_indented_headings(file_content)

    for heading in sorted(found, key=lambda h: h.line_number):
        if heading.level != 2:
            continue

        keyword, _, rest = heading.text.partition(" ")
        if keyword not in ALL_STATES:
            continue

        # Walk the :PROPERTIES: drawer that follows the heading, if any.
        custom_id = ""
        for line in lines[heading.line_number : heading.line_number + 20]:
            stripped = line.strip()
            if stripped == ":END:" or HEADING_RE.match(line):
                break
            if stripped.upper().startswith(":CUSTOM_ID:"):
                custom_id = stripped.split(":", 2)[2].strip()
                break

        identities.append(custom_id or f"headline:{_strip_tags(rest)}")

    return identities


###############################################################################
#
def heading_matches(heading: Heading, identifier: str) -> bool:
    """
    Report whether a heading is the task named by ``identifier``.

    Args:
        heading: A level-2 task heading
        identifier: ``:CUSTOM_ID:``, a bare id without the ``task-`` prefix,
            or a substring of the headline

    Returns:
        True when the heading is that task.

    Note:
        Deliberately the same matching :func:`find_task` performs, so naming
        a task in ``relative_to`` works exactly as naming one anywhere else.
    """
    properties = _properties(heading)
    headline = (
        heading.headline.title
        if hasattr(heading.headline, "title")
        else str(heading.headline)
    )
    wanted = identifier.strip().lower()

    return (
        properties.CUSTOM_ID == identifier
        or properties.CUSTOM_ID == f"task-{wanted}"
        or wanted in headline.lower()
    )


###############################################################################
#
def placement_index(
    children: list[Heading],
    position: str,
    relative_to: str | None = None,
) -> int:
    """
    Work out where in a section a task should be inserted.

    Args:
        children: The section's tasks, excluding the one being placed
        position: One of ``top``, ``bottom``, ``before`` or ``after``
        relative_to: Task to position against, required by ``before`` and
            ``after``

    Returns:
        The index to insert at.

    Raises:
        ValueError: If the position is unknown, if ``before``/``after`` is
            given without ``relative_to``, or if ``relative_to`` names no task
            in this section.

    Note:
        ``before`` and ``after`` express ordering only. A task placed after
        another is follow-on work, not work blocked by it, and may proceed
        while the other is still open -- so nothing here implies a dependency.
    """
    match position:
        case "top":
            return 0
        case "bottom":
            return len(children)
        case "before" | "after":
            if not relative_to:
                raise ValueError(
                    f"position '{position}' needs relative_to naming the task "
                    f"to position against"
                )
            for idx, child in enumerate(children):
                if heading_matches(child, relative_to):
                    return idx if position == "before" else idx + 1
            raise ValueError(
                f"Cannot position {position} '{relative_to}': no such task in "
                f"this section"
            )
        case _:
            raise ValueError(
                f"Unknown position '{position}'. Use one of: "
                f"{', '.join(POSITIONS)}"
            )


###############################################################################
#
def place_child(
    section: Heading,
    child: Heading,
    position: str = "top",
    relative_to: str | None = None,
) -> None:
    """
    Add a task to a section at a chosen position.

    Args:
        section: The section heading to add to
        child: The task heading to place
        position: One of ``top``, ``bottom``, ``before`` or ``after``
        relative_to: Task to position against, for ``before`` and ``after``

    Note:
        Position in a section is priority, so every path that files a task
        goes through here rather than appending. Appending is what filed new
        and reopened work at the bottom, which is where a task ends up when it
        has been passed over -- the opposite of what either means.

        ``add_child`` is still what does the adopting: it sets the parent and
        appends. This lifts the task back off the end and inserts it where it
        belongs.
    """
    section.add_child(child, new=True)

    children = list(section.children)
    placed = children.pop()
    children.insert(placement_index(children, position, relative_to), placed)
    section.children = children


###############################################################################
#
def scan_section_headings(file_content: str) -> list[str]:
    """
    List every level-1 section in a tasks.org file by scanning the raw text.

    Args:
        file_content: Full text of a tasks.org file

    Returns:
        Section names in file order, with tags and any trailing progress
        cookie removed so a section is the same section before and after its
        cookie is recounted or its tags are realigned.

    Note:
        Like :func:`scan_task_identities` this deliberately does NOT go
        through orgmunge.  A section the parser cannot see is precisely what
        this is here to notice, so asking the parser would defeat it.

        Tags and cookies are stripped for the same reason they are stripped
        from task identities: orgmunge re-renders both, and a name that does
        not survive a round trip would make the write guard refuse every
        write with no way for the caller to comply.
    """
    return [
        SECTION_COOKIE_RE.sub("", _strip_tags(heading.text)).strip()
        for heading in scan_headings(file_content)
        if heading.level == 1
    ]


###############################################################################
#
def write_tasks_org(org: Org, summary: str, target: str | None = None) -> None:
    """
    Serialise and write the tasks file, refusing writes that lose a task.

    Args:
        org: The Org object to write
        summary: Short description of the change for the git commit message
        target: Identity (``:CUSTOM_ID:`` or ``headline:<text>``) of the one
            task this operation is allowed to remove or rename.  ``None`` means
            the operation must not remove any task at all.

    Raises:
        ValueError: If any task other than ``target``, or any section heading,
            would disappear.  The file is left untouched.

    Note:
        This is the backstop for the whole module.  Whatever else goes wrong --
        a parser that loses a heading, a bad rewrite, a malformed entry that
        slipped past validation -- no write may ever delete a task the caller
        did not name.  Correctness here does not depend on knowing *why* a task
        went missing, only that it did.

        Sections are checked as well as tasks, because a lost section does not
        have to take a task with it.  When a swallowed region ends before the
        first task under a heading, every task identity still matches and only
        the heading dies -- which is how "* Completed Tasks" was destroyed on
        2026-08-28 with the task guard already in place.
    """
    tasks_file = global_state.config.tasks_file
    new_content = str(org)

    old_content = (
        tasks_file.read_text(encoding="utf-8") if tasks_file.exists() else ""
    )

    before = scan_task_identities(old_content)
    after = scan_task_identities(new_content)

    allowed = {target} if target else set()
    vanished = [i for i in before if i not in set(after) and i not in allowed]

    if vanished:
        lost = "\n".join(f"  - {identity}" for identity in vanished)
        raise ValueError(
            f"Refusing to write {tasks_file}: the operation would remove "
            f"{len(vanished)} task(s) it was not asked to touch:\n\n{lost}\n\n"
            f"The file has been left unchanged. This usually means the org "
            f"parser lost track of a heading; re-read the task with get_task "
            f"and retry, or inspect the file directly."
        )

    sections_after = set(scan_section_headings(new_content))
    dropped = [
        name
        for name in scan_section_headings(old_content)
        if name not in sections_after
    ]

    if dropped:
        lost = "\n".join(f"  - {name}" for name in dropped)
        raise ValueError(
            f"Refusing to write {tasks_file}: the operation would remove "
            f"{len(dropped)} section heading(s):\n\n{lost}\n\n"
            f"The file has been left unchanged. No task operation removes a "
            f"section, so the parser has lost track of one; run list_tasks to "
            f"see what it can no longer resolve, or inspect the file directly."
        )

    write_file(tasks_file, new_content, summary=summary)


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

    # Before reporting a plain "not found", check whether the file contains
    # tasks the parser cannot see -- that is a very different problem and the
    # caller needs to know it rather than assume the task never existed.
    message = f"Could not find task '{identifier}' in section '{section}'"
    if unparsed := find_unparsed_tasks():
        message += "\n" + "\n".join(format_unparsed_warning(unparsed))
    raise ValueError(message)


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

        Validation happens here rather than in the tool layer so that every
        path into the parser is covered.  orgmunge silently keeps only the
        first level-2 heading, so an unvalidated entry with a stray sibling
        loses everything after it while still reporting success.
    """
    task_entry = validate_task_entry(task_entry)

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
def create_task(
    section_name: str,
    task_entry: str,
    position: str = "top",
    relative_to: str | None = None,
) -> tuple[str, str]:
    """
    Add a new task to the specified section.

    Args:
        section_name: Section to add the task to
        task_entry: Complete org-formatted task entry string
        position: Where to file it in the section -- one of top, bottom,
            before or after. Defaults to top, because this operation is itself
            a statement that the work matters.
        relative_to: Task to position against, required by before and after

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

    place_child(target_section, new_task, position, relative_to)

    # Add to High Level Tasks checklist if creating in active section
    if section_name == global_state.config.active_section:
        headline_title = (
            new_task.headline.title
            if hasattr(new_task.headline, "title")
            else str(new_task.headline)
        )
        description = extract_task_description(headline_title)
        add_high_level_task(org, description)

    # A create must not remove anything, so no task is exempt from the guard.
    write_tasks_org(org, summary=f"create task {custom_id}")

    # Return section and the task content for formatting
    return (section_name, heading_to_org_string(new_task))


###############################################################################
#
def update_task(
    identifier: str,
    new_task_entry: str,
    position: str = "top",
    relative_to: str | None = None,
) -> tuple[Task, str, bool, str, str]:
    """
    Replace a task with new content, moving sections if status changed.

    Args:
        identifier: String to find the task (CUSTOM_ID, ticket ID, or headline)
        new_task_entry: Complete org-mode task entry as a string
        position: Where to file it when the status change moves it to another
            section. Ignored when the task stays put, since an edit says
            nothing about priority and must not quietly promote a task.
        relative_to: Task to position against, required by before and after

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
        # Changing section is a priority statement in itself -- finishing work
        # or reopening it -- so the task goes to the top rather than the
        # bottom, where passed-over work accumulates.
        old_section_heading.remove_child(old_heading)
        place_child(target_section, new_task, position, relative_to)

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

    # The target task is the only one allowed to change identity here: its
    # replacement carries the same :CUSTOM_ID:, so it should still be present
    # afterwards, but exempt it so a deliberate rename cannot trip the guard.
    identity = task.custom_id or f"headline:{task.headline}"
    write_tasks_org(
        org,
        summary=f"update task {task.custom_id or task.headline}",
        target=identity,
    )

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
def section_identities(section: Heading) -> list[str]:
    """
    List the tasks in a section, by identity, in order.

    Args:
        section: A section heading

    Returns:
        ``:CUSTOM_ID:`` where a task has one, otherwise ``headline:<text>``.
    """
    identities: list[str] = []

    for child in section.children:
        if child.headline.level != 2:
            continue
        if child.headline.todo not in ALL_STATES:
            continue

        headline = (
            child.headline.title
            if hasattr(child.headline, "title")
            else str(child.headline)
        )
        identities.append(
            _properties(child).CUSTOM_ID or f"headline:{headline}"
        )

    return identities


###############################################################################
#
def reorder_task(
    identifier: str,
    position: str = "top",
    relative_to: str | None = None,
) -> tuple[str, str, int]:
    """
    Move a task within its own section, without changing it.

    Args:
        identifier: String to find the task
        position: One of ``top``, ``bottom``, ``before`` or ``after``
        relative_to: Task to position against, for ``before`` and ``after``

    Returns:
        Tuple of (headline, section name, new 1-based position).

    Raises:
        ValueError: If the task is not found, the position is unknown, or the
            reorder would change which tasks the section holds.

    Note:
        A reorder is a pure permutation, which admits a stricter check than
        the general write guard: the section must hold exactly the same tasks
        afterwards, in some order. That is cheap and exact, and it guards the
        children-list surgery this performs.

        There is no ediff approval here. Nothing about the task changes, so
        there is no diff of its content to show -- only its position moves,
        and that is what the caller asked for.

        Works in any section. Completed tasks are usually newest-first, but
        may be reordered by other logic on request.
    """
    task, heading, section, org = find_task(identifier)

    section_name = (
        section.headline.title
        if hasattr(section.headline, "title")
        else str(section.headline)
    ).strip()

    before = section_identities(section)

    section.remove_child(heading)
    place_child(section, heading, position, relative_to)

    after = section_identities(section)

    if sorted(before) != sorted(after):
        lost = sorted(set(before) - set(after))
        gained = sorted(set(after) - set(before))
        raise ValueError(
            f"Refusing to reorder: '{section_name}' would no longer hold the "
            f"same tasks. A reorder must only permute them.\n"
            f"  missing after: {lost or 'none'}\n"
            f"  appeared after: {gained or 'none'}"
        )

    write_tasks_org(
        org,
        summary=(
            f"reorder task {task.custom_id or task.headline} to {position}"
            + (f" {relative_to}" if relative_to else "")
        ),
    )

    identity = task.custom_id or f"headline:{task.headline}"

    return (task.headline, section_name, after.index(identity) + 1)


###############################################################################
#
def resort_completed_tasks() -> tuple[int, int]:
    """
    Sort the completed section newest-first by ``:CLOSED:``.

    Returns:
        Tuple of (tasks in the section, how many changed position).

    Raises:
        ValueError: If the completed section cannot be found, or if the sort
            would change which tasks it holds.

    Note:
        Deliberately not automatic. New completions go to the top from now on,
        which leaves a seam above tasks completed before that was true; this
        is the one-off that closes the seam, and it exists to be run on
        request rather than to run itself. Completed order may also be
        meaningful for other reasons, and this would overwrite that.

        Tasks with no ``:CLOSED:`` sort last, in their existing relative
        order, since there is nothing to place them by and inventing a date
        would be worse than leaving them where they are.
    """
    org = get_org()
    section_name = global_state.config.completed_section
    section = find_section(org, section_name)

    if section is None:
        raise ValueError(f"Section not found: {section_name}")

    before_order = section_identities(section)
    children = list(section.children)

    # Sort key: CLOSED descending, then original position ascending so that
    # anything without a date keeps its relative order rather than shuffling.
    def sort_key(item: tuple[int, Heading]) -> tuple[int, str, int]:
        idx, child = item
        closed = _properties(child).CLOSED or ""
        return (0 if closed else 1, closed and _invert(closed) or "", idx)

    section.children = [
        child for _, child in sorted(enumerate(children), key=sort_key)
    ]

    after_order = section_identities(section)

    if sorted(before_order) != sorted(after_order):
        raise ValueError(
            f"Refusing to re-sort '{section_name}': the section would no "
            f"longer hold the same tasks. A sort must only permute them."
        )

    moved = sum(
        1 for a, b in zip(before_order, after_order, strict=True) if a != b
    )

    write_tasks_org(
        org, summary=f"re-sort {section_name} newest first by CLOSED"
    )

    return (len(after_order), moved)


###############################################################################
#
def _invert(timestamp: str) -> str:
    """
    Return a sort key that orders timestamps newest first.

    Args:
        timestamp: An org timestamp such as ``<2026-08-31 Mon 14:29>``

    Returns:
        A string that sorts in reverse chronological order.

    Note:
        Org timestamps sort correctly as text because the date is written
        most-significant first, so reversing is a matter of complementing each
        digit rather than parsing a date.
    """
    return "".join(
        str(9 - int(char)) if char.isdigit() else char for char in timestamp
    )


###############################################################################
#
def move_task(
    identifier: str,
    from_section: str,
    to_section: str,
    position: str = "top",
    relative_to: str | None = None,
) -> tuple[str, str, str]:
    """
    Move a task from one section to another.

    Args:
        identifier: String to find the task
        from_section: Source section name
        to_section: Destination section name
        position: Where to file it in the section -- one of top, bottom,
            before or after. Defaults to top, because this operation is itself
            a statement that the work matters.
        relative_to: Task to position against, required by before and after

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
    place_child(target_section, heading, position, relative_to)

    # A move relocates a task but must not remove one, so nothing is exempt.
    write_tasks_org(
        org,
        summary=(
            f"move task {task.custom_id or task.headline} to {to_section}"
        ),
    )

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
def find_unparsed_tasks() -> list[str]:
    """
    List tasks present in tasks.org that the org parser does not see.

    Returns:
        Identities (``:CUSTOM_ID:`` or ``headline:<text>``) of tasks found by
        scanning the raw file but absent from every parsed section.

    Note:
        A non-empty result means the file is structurally confusing the parser
        -- typically a stray heading that has re-parented everything after it.
        Those tasks are invisible to get_task and list_tasks, which is how a
        task can appear to have vanished while still being in the file.
    """
    tasks_file = global_state.config.tasks_file
    if not tasks_file.exists():
        return []

    in_file = scan_task_identities(tasks_file.read_text(encoding="utf-8"))

    parsed: set[str] = set()
    for section_name in (
        global_state.config.active_section,
        global_state.config.completed_section,
    ):
        for task in list_tasks(section_name):
            parsed.add(task.custom_id or f"headline:{task.headline}")

    return [identity for identity in in_file if identity not in parsed]


###############################################################################
#
def find_lost_sections() -> list[str]:
    """
    List section headings present in tasks.org that the parser cannot resolve.

    Returns:
        Names of configured sections that exist as ``* <name>`` in the raw file
        but which :func:`find_section` does not find.

    Note:
        A lost section is worse than a lost task.  Every task under it is
        absorbed into the section before it, so they are still *parsed* -- just
        filed under the wrong heading.  That makes completed tasks show up as
        active, which :func:`find_unparsed_tasks` cannot catch, because from
        its point of view nothing went missing.
    """
    tasks_file = global_state.config.tasks_file
    if not tasks_file.exists():
        return []

    content = tasks_file.read_text(encoding="utf-8")
    org = get_org()

    lost: list[str] = []
    for name in (
        global_state.config.active_section,
        global_state.config.completed_section,
        global_state.config.high_level_section,
    ):
        if find_section(org, name) is not None:
            continue

        # Look for the heading by name rather than through scan_headings: an
        # indented "* Completed Tasks" is one of the ways a section gets lost,
        # and the general scanners deliberately ignore a lone indented star
        # because it is normally a list bullet.  Matching an exact section name
        # removes that ambiguity.
        pattern = re.compile(
            rf"^[ \t]*\*+[ \t]+{re.escape(name)}[ \t]*(?:\[\d*/\d*\])?[ \t]*$"
        )
        if any(pattern.match(line) for line in content.split("\n")):
            lost.append(name)

    return lost


###############################################################################
#
def format_unparsed_warning(unparsed: list[str]) -> list[str]:
    """
    Render a warning block for tasks the parser cannot see.

    Args:
        unparsed: Identities returned by :func:`find_unparsed_tasks`

    Returns:
        Lines to append to tool output, or an empty list if nothing is wrong.

    Note:
        Also reports sections the parser has lost, which is a more serious
        condition: the tasks under them are silently filed under the wrong
        heading rather than going missing.
    """
    lines: list[str] = []

    if lost := find_lost_sections():
        lines.extend(
            [
                "",
                f"⚠ WARNING: {len(lost)} section heading(s) exist in the file "
                "but the parser cannot see them:",
            ]
        )
        lines.extend(f"    * {name}" for name in lost)
        lines.append(
            "  Every task under them has been absorbed into the section above, "
            "so they are reported under the wrong heading -- completed tasks "
            "will appear as active. Repair the file structure."
        )

    if unparsed:
        lines.extend(
            [
                "",
                f"⚠ WARNING: {len(unparsed)} task(s) exist in the file but are "
                "not visible to the parser:",
            ]
        )
        lines.extend(f"    {identity}" for identity in unparsed)
        lines.append(
            "  They cannot be found or updated until the file structure is "
            "repaired -- look for a stray heading that has re-parented them."
        )

    return lines


###############################################################################
#
def task_to_record(task: Task) -> Record:
    """
    Adapt a task to the shared result envelope.

    Args:
        task: The task to adapt

    Returns:
        A :class:`Record` with the task's columns rendered.

    Note:
        The ``:MODIFIED:`` age rides along because position in a section
        encodes priority: a task drifts down as it goes unpicked, so "near the
        bottom and untouched for three months" is the judgement being made
        when scanning a list, and it cannot be made from the headline alone.
    """
    ticket = f"[{task.ticket_id}] " if task.ticket_id else ""
    identity = f"(#{task.custom_id})" if task.custom_id else ""
    age = format_age(task.modified or task.created)

    return Record(
        ref=task.custom_id or task.headline,
        prefix=task.status,
        title=f"{ticket}{task.headline}",
        suffix=" ".join(part for part in (identity, age) if part),
        content=task.content,
    )


###############################################################################
#
def task_warnings() -> list[str]:
    """
    Return the warning block about tasks and sections the parser cannot see.

    Returns:
        Lines to hand to :func:`~mcp_server.results.render` as ``warnings``,
        or an empty list when the file is healthy.

    Note:
        Every listing and search of tasks must surface this, so it is computed
        in one place and passed into the envelope rather than appended by each
        caller. Anything appended after a result body can be paged past, and
        this is the report that a task has become invisible.
    """
    return format_unparsed_warning(find_unparsed_tasks())


###############################################################################
#
def format_task_list(
    tasks: list[Task],
    section: str,
    detail: DetailLevel = "index",
    limit: int | None = None,
    offset: int = 0,
) -> str:
    """
    Format a list of tasks for display.

    Args:
        tasks: List of tasks to format, in file order
        section: Section name for the header
        detail: Envelope detail level
        limit: Maximum tasks to show; None takes the level's default
        offset: Tasks to skip

    Returns:
        A rendered page. The result numbering is the task's position in its
        section, which is what encodes priority, and any parser warning is
        carried on every page.
    """
    return render(
        [task_to_record(task) for task in tasks],
        tool="list_tasks",
        header=section,
        detail=detail,
        limit=limit,
        offset=offset,
        warnings=task_warnings(),
    )


###############################################################################
#
def format_task_search(
    tasks: list[Task],
    query: str,
    detail: DetailLevel = "snippet",
    limit: int | None = None,
    offset: int = 0,
) -> str:
    """
    Format task search results.

    Args:
        tasks: Matching tasks
        query: The query that produced them, used to build snippets
        detail: Envelope detail level, defaulting to snippet so a result shows
            why it matched and not merely that it did
        limit: Maximum matches to show; None takes the level's default
        offset: Matches to skip

    Returns:
        A rendered page carrying the same parser warning as a listing. A task
        hidden from the parser makes search miss it silently, or answer with
        the task that absorbed it, so the warning matters most here.
    """
    return render(
        [task_to_record(task) for task in tasks],
        tool="search_tasks",
        header=f'search_tasks("{query}")',
        detail=detail,
        limit=limit,
        offset=offset,
        query=query,
        warnings=task_warnings(),
    )


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
