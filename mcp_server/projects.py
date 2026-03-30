"""
Project operations: data structure, parsing, CRUD, and formatting.
"""

# system imports
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

# project imports
from mcp_server.config import global_state, logger
from mcp_server.utils import (
    backup_file,
    format_simple_diff,
    get_current_timestamp,
    request_ediff_approval,
    write_file,
)

# =============================================================================
# Constants
# =============================================================================

# Properties managed on project files
PROJECT_PROPERTIES = (
    "CUSTOM_ID",
    "ID",
    "CREATED",
    "MODIFIED",
    "STATUS",
    "REPO",
)
VALID_PROJECT_STATUSES = ("active", "on-hold", "completed", "planning")

# The standard sections in a project file, in canonical order.
PROJECT_SECTIONS = (
    "Description",
    "Design",
    "Goals",
    "Related Tasks",
    "Related Links",
    "Notes",
)


# =============================================================================
# Project Data Structure
# =============================================================================

# Regex for parsing a level-1 org heading with optional tags
_PROJECT_HEADING_RE = re.compile(r"^\*\s+(.+?)(?:\s+:((?:[^:]+:)+))?\s*$")

# Regex for a properties drawer line
_PROPERTY_RE = re.compile(r"^\s*:([A-Z_]+):\s+(.+?)\s*$")


###############################################################################
###############################################################################
#
@dataclass
class Project:
    """Represents an org-mode project file."""

    title: str  # Project headline text
    slug: str  # Derived from CUSTOM_ID (e.g., "booklore")
    custom_id: str  # :CUSTOM_ID: value (e.g., "project-booklore")
    id: str  # UUID from :ID:
    status: str  # active, on-hold, completed, planning
    tags: list[str]  # Org tags on the heading
    created: str  # :CREATED: timestamp
    modified: str  # :MODIFIED: timestamp
    repo: str  # :REPO: URL or empty string
    sections: dict[str, str]  # Section name -> content mapping
    file_path: Path  # Path to the .org file
    raw_content: str  # Full file content for reference

    ###########################################################################
    #
    @property
    def description(self) -> str:
        """Return the Description section content."""
        return self.sections.get("Description", "")

    ###########################################################################
    #
    @property
    def goals(self) -> str:
        """Return the Goals section content."""
        return self.sections.get("Goals", "")

    ###########################################################################
    #
    def to_org(self) -> str:
        """Serialize project back to org format."""
        tags_str = f"  :{':'.join(self.tags)}:" if self.tags else ""
        lines = [f"* {self.title}{tags_str}"]

        # Properties drawer
        lines.append(":PROPERTIES:")
        lines.append(f"   :ID:       {self.id}")
        lines.append(f"   :CUSTOM_ID: {self.custom_id}")
        lines.append(f"   :CREATED:  {self.created}")
        lines.append(f"   :MODIFIED: {self.modified}")
        lines.append(f"   :STATUS:   {self.status}")
        if self.repo:
            lines.append(f"   :REPO:     {self.repo}")
        lines.append(":END:")

        # Sections in canonical order, then any extras
        written = set()
        for section_name in PROJECT_SECTIONS:
            if section_name in self.sections:
                lines.append("")
                lines.append(f"** {section_name}")
                content = self.sections[section_name].rstrip()
                if content:
                    lines.append(content)
                written.add(section_name)

        # Any non-standard sections
        for section_name, content in self.sections.items():
            if section_name not in written:
                lines.append("")
                lines.append(f"** {section_name}")
                content = content.rstrip()
                if content:
                    lines.append(content)

        return "\n".join(lines) + "\n"


# =============================================================================
# Project Parsing
# =============================================================================


###############################################################################
#
def get_project_path(slug: str) -> Path:
    """Return the file path for a project by slug."""
    return global_state.config.projects_dir / f"{slug}.org"


###############################################################################
#
def parse_project_properties(
    lines: list[str], start_idx: int
) -> tuple[dict[str, str], int]:
    """
    Parse a :PROPERTIES: drawer from lines starting at start_idx.

    Args:
        lines: All lines in the file
        start_idx: Index of the :PROPERTIES: line

    Returns:
        Tuple of (properties dict, index of line after :END:)
    """
    props: dict[str, str] = {}
    idx = start_idx + 1  # Skip :PROPERTIES: line
    while idx < len(lines):
        line = lines[idx].strip()
        if line == ":END:":
            return props, idx + 1
        m = _PROPERTY_RE.match(lines[idx])
        if m:
            props[m.group(1)] = m.group(2)
        idx += 1
    return props, idx


###############################################################################
#
def parse_project_sections(lines: list[str], start_idx: int) -> dict[str, str]:
    """
    Parse level-2 sections from a project file.

    Args:
        lines: All lines in the file
        start_idx: Index to start scanning for ** headings

    Returns:
        Dict mapping section name to content (text between headings)
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if line.startswith("** "):
            # Save previous section
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines)
            # Extract section name — strip any trailing org cookie
            # like [2/5]
            heading_text = line[3:].strip()
            # Remove progress cookie for the key but keep it parseable
            name_match = re.match(
                r"^(.+?)(?:\s+\[\d*/\d*\])?\s*$", heading_text
            )
            current_name = name_match.group(1) if name_match else heading_text
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    # Save last section
    if current_name is not None:
        sections[current_name] = "\n".join(current_lines)

    return sections


###############################################################################
#
def parse_project_file(file_path: Path) -> Project:
    """
    Parse a project .org file into a Project object.

    Args:
        file_path: Path to the project .org file

    Returns:
        Project object with all parsed fields

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If the file has no valid level-1 heading
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Project file not found: {file_path}")

    raw_content = file_path.read_text()
    lines = raw_content.split("\n")

    # Find level-1 heading
    title = ""
    tags: list[str] = []
    heading_idx = -1
    for idx, line in enumerate(lines):
        m = _PROJECT_HEADING_RE.match(line)
        if m and line.startswith("* "):
            title = m.group(1).strip()
            if m.group(2):
                tags = [t for t in m.group(2).split(":") if t]
            heading_idx = idx
            break

    if heading_idx == -1:
        raise ValueError(f"No level-1 heading found in {file_path}")

    # Parse properties drawer
    props: dict[str, str] = {}
    content_start = heading_idx + 1
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].strip() == ":PROPERTIES:":
            props, content_start = parse_project_properties(lines, idx)
            break
        elif lines[idx].strip() and not lines[idx].startswith("#"):
            # Non-empty, non-comment line before properties means
            # no properties drawer.
            content_start = idx
            break

    # Parse sections
    sections = parse_project_sections(lines, content_start)

    custom_id = props.get("CUSTOM_ID", "")
    slug = custom_id.removeprefix("project-") if custom_id else (file_path.stem)

    return Project(
        title=title,
        slug=slug,
        custom_id=custom_id,
        id=props.get("ID", ""),
        status=props.get("STATUS", ""),
        tags=tags,
        created=props.get("CREATED", ""),
        modified=props.get("MODIFIED", ""),
        repo=props.get("REPO", ""),
        sections=sections,
        file_path=file_path,
        raw_content=raw_content,
    )


# =============================================================================
# Project Helpers
# =============================================================================


###############################################################################
#
def replace_project_section(
    file_content: str, section_name: str, new_content: str
) -> str:
    """
    Replace a level-2 section's content in a project file.

    If the section does not exist, it is appended at the end.
    Preserves the section heading line; only replaces the body.

    Args:
        file_content: Full file content
        section_name: Name of the ** section to replace
        new_content: New body content for the section

    Returns:
        Updated file content
    """
    lines = file_content.split("\n")
    section_heading_idx: int | None = None
    section_end_idx: int | None = None

    # Match section heading, allowing for optional progress cookie
    pattern = re.compile(
        rf"^\*\*\s+{re.escape(section_name)}(?:\s+\[\d*/\d*\])?\s*$"
    )

    for idx, line in enumerate(lines):
        if pattern.match(line):
            section_heading_idx = idx
        elif section_heading_idx is not None and line.startswith("** "):
            section_end_idx = idx
            break

    if section_heading_idx is None:
        # Section doesn't exist — append it
        content = file_content.rstrip("\n")
        return f"{content}\n\n** {section_name}\n{new_content}\n"

    if section_end_idx is None:
        section_end_idx = len(lines)

    # Replace content between heading and next section
    new_body_lines = new_content.split("\n") if new_content else []
    new_lines = (
        lines[: section_heading_idx + 1]
        + new_body_lines
        + lines[section_end_idx:]
    )
    return "\n".join(new_lines)


###############################################################################
#
def update_project_properties(file_content: str, props: dict[str, str]) -> str:
    """
    Update properties in a project file's :PROPERTIES: drawer.

    Existing properties are updated; new ones are added before :END:.

    Args:
        file_content: Full file content
        props: Dict of property name -> value to set

    Returns:
        Updated file content
    """
    lines = file_content.split("\n")
    prop_start: int | None = None
    prop_end: int | None = None

    for idx, line in enumerate(lines):
        if line.strip() == ":PROPERTIES:":
            prop_start = idx
        elif line.strip() == ":END:" and prop_start is not None:
            prop_end = idx
            break

    if prop_start is None or prop_end is None:
        return file_content

    # Collect existing properties with their positions
    remaining = dict(props)
    new_prop_lines: list[str] = []
    for idx in range(prop_start + 1, prop_end):
        m = _PROPERTY_RE.match(lines[idx])
        if m and m.group(1) in remaining:
            # Replace this property's value
            key = m.group(1)
            new_prop_lines.append(
                f"   :{key}:{' ' * max(1, 9 - len(key))}{remaining[key]}"
            )
            del remaining[key]
        else:
            new_prop_lines.append(lines[idx])

    # Add any new properties before :END:
    for key, value in remaining.items():
        new_prop_lines.append(f"   :{key}:{' ' * max(1, 9 - len(key))}{value}")

    new_lines = lines[: prop_start + 1] + new_prop_lines + lines[prop_end:]
    return "\n".join(new_lines)


###############################################################################
#
def slugify_title(title: str) -> str:
    """
    Convert a project title to a filename-safe slug.

    Args:
        title: Project title string

    Returns:
        Lowercase slug with hyphens instead of spaces
    """
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug


###############################################################################
#
def regenerate_project_index() -> None:
    """
    Regenerate ~/org/projects/index.org from all project files.

    Groups projects by status and writes org-mode links with
    description previews.
    """
    projects_dir = global_state.config.projects_dir
    if not projects_dir.exists():
        return

    projects: list[Project] = []
    for f in sorted(projects_dir.glob("*.org")):
        if f.name == "index.org":
            continue
        try:
            projects.append(parse_project_file(f))
        except (ValueError, FileNotFoundError):
            logger.warning("Skipping unparseable project: %s", f)

    # Group by status
    groups: dict[str, list[Project]] = {}
    for status in VALID_PROJECT_STATUSES:
        groups[status] = []
    for p in projects:
        status = p.status if p.status in groups else "planning"
        groups[status].append(p)

    # Build index content
    lines = [
        "* Projects Index",
        "Auto-generated index of all projects. Do not edit manually.",
        "",
    ]

    status_labels = {
        "active": "Active",
        "planning": "Planning",
        "on-hold": "On Hold",
        "completed": "Completed",
    }

    for status, label in status_labels.items():
        group = groups.get(status, [])
        if not group:
            continue
        lines.append(f"** {label}")
        for p in sorted(group, key=lambda x: x.title):
            desc_line = p.description.strip().split("\n")[0][:80]
            link = f"[[file:{p.file_path}][{p.title}]]"
            lines.append(f"- {link} - {desc_line}")
        lines.append("")

    index_path = projects_dir / "index.org"
    write_file(index_path, "\n".join(lines))


# =============================================================================
# Project CRUD Operations
# =============================================================================


###############################################################################
#
def list_projects(
    status: str | None = None,
) -> list[Project]:
    """
    List all projects, optionally filtered by status.

    Args:
        status: Filter by project status (active, on-hold, etc.)

    Returns:
        List of Project objects sorted by title
    """
    projects_dir = global_state.config.projects_dir
    if not projects_dir.exists():
        return []

    projects: list[Project] = []
    for f in sorted(projects_dir.glob("*.org")):
        if f.name == "index.org":
            continue
        try:
            p = parse_project_file(f)
            if status is None or p.status == status:
                projects.append(p)
        except (ValueError, FileNotFoundError):
            logger.warning("Skipping unparseable project: %s", f)

    return sorted(projects, key=lambda p: p.title)


###############################################################################
#
def get_project(identifier: str) -> Project:
    """
    Find a project by slug, CUSTOM_ID, or title substring.

    Args:
        identifier: Project slug, CUSTOM_ID, or title substring

    Returns:
        Matching Project object

    Raises:
        ValueError: If no project matches
    """
    projects_dir = global_state.config.projects_dir

    # Try direct file lookup first (by slug)
    for slug_candidate in (
        identifier,
        identifier.removeprefix("project-"),
    ):
        direct_path = projects_dir / f"{slug_candidate}.org"
        if direct_path.exists():
            return parse_project_file(direct_path)

    # Search all project files
    identifier_lower = identifier.lower()
    for f in sorted(projects_dir.glob("*.org")):
        if f.name == "index.org":
            continue
        try:
            p = parse_project_file(f)
        except (ValueError, FileNotFoundError):
            continue

        if (
            p.custom_id == identifier
            or p.slug == identifier
            or identifier_lower in p.title.lower()
        ):
            return p

    raise ValueError(f"No project found matching: {identifier}")


###############################################################################
#
def create_project(project_entry: str) -> tuple[str, str]:
    """
    Create a new project file from an org-formatted string.

    Auto-generates :ID:, :CREATED:, defaults :STATUS: to planning,
    and ensures :project: tag is present.

    Args:
        project_entry: Complete org-formatted project string

    Returns:
        Tuple of (slug, final file content)

    Raises:
        ValueError: If slug already exists or entry is invalid
    """
    projects_dir = global_state.config.projects_dir

    # Parse the provided entry to extract/modify properties
    lines = project_entry.split("\n")

    # Find the heading
    heading_idx = -1
    title = ""
    tags: list[str] = []
    for idx, line in enumerate(lines):
        m = _PROJECT_HEADING_RE.match(line)
        if m and line.startswith("* "):
            title = m.group(1).strip()
            if m.group(2):
                tags = [t for t in m.group(2).split(":") if t]
            heading_idx = idx
            break

    if heading_idx == -1:
        raise ValueError(
            "Project entry must start with a level-1 heading (* Title)"
        )

    # Ensure :project: tag
    if "project" not in tags:
        tags.append("project")

    # Parse existing properties
    props: dict[str, str] = {}
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].strip() == ":PROPERTIES:":
            props, _ = parse_project_properties(lines, idx)
            break

    # Auto-set properties
    if "ID" not in props:
        props["ID"] = str(uuid.uuid4()).upper()
    if "CREATED" not in props:
        props["CREATED"] = get_current_timestamp(active=True)
    if "MODIFIED" not in props:
        props["MODIFIED"] = get_current_timestamp(active=False)
    if "STATUS" not in props:
        props["STATUS"] = "planning"

    # Derive slug
    custom_id = props.get("CUSTOM_ID", "")
    if custom_id:
        slug = custom_id.removeprefix("project-")
    else:
        slug = slugify_title(title)
        custom_id = f"project-{slug}"
        props["CUSTOM_ID"] = custom_id

    # Check for duplicate
    file_path = get_project_path(slug)
    if file_path.exists():
        raise ValueError(f"Project file already exists: {file_path}")

    # Rebuild the content with updated properties and tags
    # Parse sections from the entry
    sections: dict[str, str] = {}
    section_start = heading_idx + 1
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].strip() == ":PROPERTIES:":
            # Skip past properties drawer
            for jdx in range(idx + 1, len(lines)):
                if lines[jdx].strip() == ":END:":
                    section_start = jdx + 1
                    break
            break
    sections = parse_project_sections(lines, section_start)

    project = Project(
        title=title,
        slug=slug,
        custom_id=custom_id,
        id=props["ID"],
        status=props["STATUS"],
        tags=tags,
        created=props["CREATED"],
        modified=props["MODIFIED"],
        repo=props.get("REPO", ""),
        sections=sections,
        file_path=file_path,
        raw_content="",
    )

    final_content = project.to_org()

    # Ediff approval
    approved, result_content = request_ediff_approval(
        old_content="",
        new_content=final_content,
        context_name=f"project-{slug}",
    )

    if not approved:
        raise ValueError("Project creation rejected by user")

    if result_content != final_content:
        final_content = result_content

    # Ensure projects directory exists
    projects_dir.mkdir(parents=True, exist_ok=True)

    write_file(file_path, final_content)
    regenerate_project_index()

    return slug, final_content


###############################################################################
#
def update_project(
    identifier: str,
    section: str | None = None,
    content: str | None = None,
    properties: dict[str, str] | None = None,
    headline: str | None = None,
    tags: list[str] | None = None,
) -> tuple[Project, str]:
    """
    Update a project's section, properties, or headline.

    Supports section-level updates to avoid full file replacement.
    Always updates :MODIFIED: timestamp.

    Args:
        identifier: Project slug, CUSTOM_ID, or title substring
        section: Section name to update (e.g., "Description")
        content: New content for the section
        properties: Properties to update (e.g., {"STATUS": "active"})
        headline: New headline/title
        tags: New tags list

    Returns:
        Tuple of (old Project, new file content)

    Raises:
        ValueError: If project not found or no updates provided
    """
    if not any([section, properties, headline, tags is not None]):
        raise ValueError(
            "At least one of section, properties, headline, "
            "or tags must be provided"
        )

    project = get_project(identifier)
    old_content = project.raw_content
    new_content = old_content

    # Apply section update
    if section and content is not None:
        new_content = replace_project_section(new_content, section, content)

    # Apply property updates
    prop_updates: dict[str, str] = {}
    if properties:
        # Validate STATUS if provided
        if "STATUS" in properties:
            if properties["STATUS"] not in VALID_PROJECT_STATUSES:
                raise ValueError(
                    f"Invalid status: {properties['STATUS']}. "
                    f"Valid: {', '.join(VALID_PROJECT_STATUSES)}"
                )
        prop_updates.update(properties)

    # Always update MODIFIED
    prop_updates["MODIFIED"] = get_current_timestamp(active=False)
    new_content = update_project_properties(new_content, prop_updates)

    # Apply headline/tags update
    if headline is not None or tags is not None:
        file_lines = new_content.split("\n")
        for idx, line in enumerate(file_lines):
            if _PROJECT_HEADING_RE.match(line) and line.startswith("* "):
                new_title = headline if headline else project.title
                if tags is not None:
                    tags_str = f"  :{':'.join(tags)}:" if tags else ""
                else:
                    tags_str = (
                        f"  :{':'.join(project.tags)}:" if project.tags else ""
                    )
                file_lines[idx] = f"* {new_title}{tags_str}"
                break
        new_content = "\n".join(file_lines)

    # Ediff approval
    approved, result_content = request_ediff_approval(
        old_content=old_content,
        new_content=new_content,
        context_name=f"project-{project.slug}",
    )

    if not approved:
        raise ValueError("Project update rejected by user")

    if result_content != new_content:
        new_content = result_content

    # Write with backup
    backup_path = backup_file(project.file_path)
    write_file(project.file_path, new_content)
    if backup_path and backup_path.exists():
        backup_path.unlink()

    regenerate_project_index()

    return project, new_content


###############################################################################
#
def search_projects(query: str) -> list[Project]:
    """
    Search across all projects by query string.

    Case-insensitive substring match on title and all section content.

    Args:
        query: Search query string

    Returns:
        List of matching Project objects
    """
    query_lower = query.lower()
    matches: list[Project] = []

    for p in list_projects():
        searchable = p.title.lower()
        for section_content in p.sections.values():
            searchable += " " + section_content.lower()
        if query_lower in searchable:
            matches.append(p)

    return matches


###############################################################################
#
def link_task_to_project(project_identifier: str, task_link: str) -> str:
    """
    Add a task link to a project's Related Tasks section.

    Args:
        project_identifier: Project slug, CUSTOM_ID, or title
        task_link: Org-mode link string (e.g.,
            "- [[file:~/org/tasks.org::#task-id][Task name]]")

    Returns:
        Updated file content
    """
    project = get_project(project_identifier)
    old_content = project.raw_content

    # Get existing Related Tasks content
    existing = project.sections.get("Related Tasks", "")
    if existing.strip():
        new_section = existing.rstrip() + "\n" + task_link
    else:
        new_section = task_link

    new_content = replace_project_section(
        old_content, "Related Tasks", new_section
    )

    # Always update MODIFIED
    new_content = update_project_properties(
        new_content,
        {"MODIFIED": get_current_timestamp(active=False)},
    )

    # Ediff approval
    approved, result_content = request_ediff_approval(
        old_content=old_content,
        new_content=new_content,
        context_name=f"project-{project.slug}",
    )

    if not approved:
        raise ValueError("Link task to project rejected by user")

    if result_content != new_content:
        new_content = result_content

    backup_path = backup_file(project.file_path)
    write_file(project.file_path, new_content)
    if backup_path and backup_path.exists():
        backup_path.unlink()

    regenerate_project_index()

    return new_content


# =============================================================================
# Project Formatting
# =============================================================================


###############################################################################
#
def format_project_list(projects: list[Project]) -> str:
    """Format a list of projects for display."""
    if not projects:
        return "No projects found"

    lines = ["Projects", "=" * 30, ""]

    for p in projects:
        desc_preview = (
            p.description.strip().split("\n")[0][:60]
            if p.description.strip()
            else "(no description)"
        )
        lines.append(f"  [{p.status}]  {p.title} ({p.slug})")
        lines.append(f"           {desc_preview}")

    return "\n".join(lines)


###############################################################################
#
def format_project_detail(project: Project) -> str:
    """Format a single project in full detail."""
    lines = [
        f"{project.title}",
        f"Slug: {project.slug}",
        f"Status: {project.status}",
        f"CUSTOM_ID: {project.custom_id}",
    ]
    if project.repo:
        lines.append(f"Repo: {project.repo}")
    lines.append(f"Created: {project.created}")
    lines.append(f"Modified: {project.modified}")
    lines.append("")
    lines.append(project.to_org())
    return "\n".join(lines)


###############################################################################
#
def format_project_create_result(slug: str, content: str) -> str:
    """Format the result of creating a project."""
    return (
        f"Project Created: {slug}\nFile: {get_project_path(slug)}\n\n{content}"
    )


###############################################################################
#
def format_project_update_result(
    old_content: str, new_content: str, slug: str
) -> str:
    """Format the result of updating a project."""
    diff = format_simple_diff(old_content, new_content)
    return (
        f"Project Updated: {slug}\n\n"
        f"Changes:\n{diff}\n\n"
        f"Final content:\n{new_content}"
    )


# =============================================================================
# Serialization Helpers
# =============================================================================


###############################################################################
#
def project_to_dict(project: Project) -> dict:
    """Convert project to dictionary for JSON output."""
    return {
        "title": project.title,
        "slug": project.slug,
        "custom_id": project.custom_id,
        "status": project.status,
        "tags": project.tags,
        "repo": project.repo,
        "created": project.created,
        "modified": project.modified,
        "sections": project.sections,
        "file_path": str(project.file_path),
    }
