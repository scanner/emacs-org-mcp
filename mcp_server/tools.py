"""
MCP tool definitions and handlers.
"""

# system imports
import os
from datetime import date, datetime

# 3rd party imports
from mcp.types import TextContent, Tool

# project imports
from mcp_server.config import global_state, server
from mcp_server.journal import (
    create_journal_entry,
    format_journal_create_result,
    format_journal_detail,
    format_journal_list,
    format_journal_update_result,
    get_journal_path,
    parse_journal_entries,
    search_journal,
    update_journal_entry,
)
from mcp_server.projects import (
    VALID_PROJECT_STATUSES,
    create_project,
    format_project_create_result,
    format_project_detail,
    format_project_list,
    format_project_update_result,
    get_project,
    link_task_to_project,
    list_projects,
    regenerate_project_index,
    search_projects,
    update_project,
)
from mcp_server.tasks import (
    create_task,
    find_task,
    format_move_result,
    format_task_create_result,
    format_task_detail,
    format_task_list,
    format_task_update_result,
    list_tasks,
    move_task,
    search_tasks,
    update_task,
)
from mcp_server.utils import (
    get_emacsclient_path,
    is_ediff_approval_enabled,
)

# =============================================================================
# Shared Formatting
# =============================================================================


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
    lines = [
        f"Found {count} {item_type}{'s' if count != 1 else ''}",
        "",
    ]

    match item_type:
        case "task":
            for task in items:
                ticket = f"[{task.ticket_id}] " if task.ticket_id else ""
                lines.append(f"  {task.status}  {ticket}{task.headline}")
        case "project":
            for project in items:
                lines.append(
                    f"  [{project.status}]  {project.title} ({project.slug})"
                )
        case _:
            for entry in items:
                tags = f" :{':'.join(entry.tags)}:" if entry.tags else ""
                lines.append(
                    f"  {entry.time}  {entry.headline}"
                    f"{tags} ({entry.file_date})"
                )

    return "\n".join(lines)


# =============================================================================
# MCP Tool Definitions
# =============================================================================


###############################################################################
#
@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return the list of all MCP tools this server provides."""
    return [
        # ----- Task Tools -----
        Tool(
            name="list_tasks",
            description=(
                "List all tasks in a section of tasks.org. Returns task names, headlines, status, and full content. "
                "Use this to check for existing tasks before creating new ones, or to get an overview of work in progress. "
                "For detailed format specifications, read the emacs-org://guide/task-format resource."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section name",
                        "enum": [
                            global_state.config.active_section,
                            global_state.config.completed_section,
                        ],
                    }
                },
                "required": ["section"],
            },
        ),
        Tool(
            name="get_task",
            description=(
                "Get a specific task by identifier (#+NAME like 'task-gh-28', ticket ID like 'GH-28', or headline substring). "
                "Returns full task content including all properties, subsections, and task items. "
                "For format specifications, read emacs-org://guide/task-format."
            ),
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
                        "enum": [
                            global_state.config.active_section,
                            global_state.config.completed_section,
                        ],
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="create_task",
            description=(
                "Create a new task in a section. Provide the complete org-formatted task entry with PROPERTIES drawer and subsections. "
                "The :ID: property is auto-generated if not provided. Always search for duplicates before creating. "
                "CREATED and MODIFIED timestamps are managed automatically. "
                "For format specifications, read emacs-org://guide/task-format."
                ""
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section to add the task to",
                        "enum": [
                            global_state.config.active_section,
                            global_state.config.completed_section,
                        ],
                    },
                    "task_entry": {
                        "type": "string",
                        "description": (
                            "Complete task in org format with heading, PROPERTIES drawer (:CUSTOM_ID: required, :ID: optional), "
                            "and subsections (*** Description, *** Task items [/], etc.). "
                            "Example: '** TODO GH-123 Task\\n:PROPERTIES:\\n:CUSTOM_ID: task-gh-123\\n:END:\\n\\n*** Task items [/]\\n- [ ] item'"
                        ),
                    },
                },
                "required": ["section", "task_entry"],
            },
        ),
        Tool(
            name="update_task",
            description=(
                "Update an existing task with new content. Provide the complete new task entry including all properties and subsections. "
                "Automatic behaviors: (1) TODO→DONE moves to Completed section and sets CLOSED timestamp, "
                "(2) DONE→TODO moves to Tasks section and clears CLOSED timestamp, "
                "(3) MODIFIED timestamp updated automatically. "
                "Preserve all PROPERTIES including :ID:, :CUSTOM_ID:, and :CREATED:. "
                "For format specifications, read emacs-org://guide/task-format. "
                ""
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Task identifier to find the task (ticket ID, CUSTOM_ID, or headline)",
                    },
                    "task_entry": {
                        "type": "string",
                        "description": "Complete new task entry in org format with all properties and subsections preserved",
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
                        "enum": [
                            global_state.config.active_section,
                            global_state.config.completed_section,
                        ],
                    },
                    "to_section": {
                        "type": "string",
                        "enum": [
                            global_state.config.active_section,
                            global_state.config.completed_section,
                        ],
                    },
                },
                "required": [
                    "identifier",
                    "from_section",
                    "to_section",
                ],
            },
        ),
        Tool(
            name="search_tasks",
            description=(
                "Search tasks by query string across all sections. Returns complete matching tasks. "
                "Use this to check for existing tasks before creating new ones, or to find tasks related to a topic. "
                ""
            ),
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
            description=(
                "List all journal entries for a specific date. Returns entry times, headlines, content, and tags. "
                "Use this to check what's already logged before creating new entries to avoid duplicates. "
                "For format specifications, read emacs-org://guide/journal-format."
            ),
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
            description=(
                "Get a specific journal entry by date and time or headline substring. Returns complete entry content. "
                "For format specifications, read emacs-org://guide/journal-format."
            ),
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
            description=(
                "Create a new journal entry with format: ** HH:MM [TICKET-ID] headline :tags:. "
                "Always check for existing entries first using list_journal_entries to avoid duplicates. "
                "Include ticket IDs (GH-123), PR links ([[url][#123]]), and task links ([[file:~/org/tasks.org::#task-id][Display]]) as appropriate. "
                "Use current system time for timestamp. Common tags: daily_summary, meeting, decision, blocked. "
                "For format specifications, read emacs-org://guide/journal-format."
                ""
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format. Defaults to today.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM format (24-hour). Defaults to current time.",
                    },
                    "headline": {
                        "type": "string",
                        "description": (
                            "Entry headline with optional ticket ID and PR/task links. "
                            "Examples: 'GH-28 Completed feature', 'GH-127 [[https://github.com/org/repo/pull/221][#221]] Submitted PR', "
                            "'Work summary'"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Entry body with bullet points (- ). Include task links using [[file:~/org/tasks.org::#task-id][Display]] format. "
                            "Focus on outcomes, decisions, and follow-ups."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags like 'daily_summary', 'meeting', 'decision', 'blocked'",
                    },
                },
                "required": ["headline", "content"],
            },
        ),
        Tool(
            name="update_journal_entry",
            description=(
                "Update an existing journal entry with new content. Finds the entry by time (HH:MM), "
                "using existing_headline to disambiguate if multiple entries share the same time. "
                "Use this to correct or enhance existing entries, or add forgotten details like task links. "
                "For format specifications, read emacs-org://guide/journal-format."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format",
                    },
                    "time": {
                        "type": "string",
                        "description": "New time in HH:MM format (24-hour)",
                    },
                    "headline": {
                        "type": "string",
                        "description": "New headline with optional ticket ID, PR links, and task links",
                    },
                    "content": {
                        "type": "string",
                        "description": "New body content with bullet points and optional task links",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated tags (replaces existing)",
                    },
                    "existing_time": {
                        "type": "string",
                        "description": "Time (HH:MM) of the entry to update. Only needed if changing the time; defaults to 'time'.",
                    },
                    "existing_headline": {
                        "type": "string",
                        "description": "Headline substring to disambiguate when multiple entries share the same time.",
                    },
                },
                "required": [
                    "date",
                    "time",
                    "headline",
                    "content",
                ],
            },
        ),
        Tool(
            name="search_journal",
            description=(
                "Search journal entries by query string across recent days. Returns complete matching entries. "
                "Use this to find past work on a topic, review recent activity, or look up when something was done. "
                "Searches last 30 days by default. "
                ""
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (matches headlines and content)",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Days to search back (default 30, searches from today backwards)",
                    },
                },
                "required": ["query"],
            },
        ),
        # ----- Project Tools -----
        Tool(
            name="list_projects",
            description=(
                "List all projects, optionally filtered by status. Returns project titles, slugs, "
                "status, and description previews. "
                "For detailed format specifications, read the emacs-org://guide/project-format resource."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by project status",
                        "enum": list(VALID_PROJECT_STATUSES),
                    },
                },
            },
        ),
        Tool(
            name="get_project",
            description=(
                "Get a specific project by identifier (slug like 'booklore', CUSTOM_ID like "
                "'project-booklore', or title substring). Returns full project content including "
                "all properties and sections. "
                "For format specifications, read emacs-org://guide/project-format."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Project slug, CUSTOM_ID, or title substring",
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="create_project",
            description=(
                "Create a new project file from a complete org-formatted string. "
                "Auto-generates :ID: (UUID), :CREATED:, and defaults :STATUS: to 'planning'. "
                "The project_entry should include a level-1 heading, :PROPERTIES: drawer with "
                ":CUSTOM_ID:, and level-2 sections (Description, Design, Goals, etc.). "
                "For format specifications, read emacs-org://guide/project-format."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_entry": {
                        "type": "string",
                        "description": "Complete org-formatted project string",
                    },
                },
                "required": ["project_entry"],
            },
        ),
        Tool(
            name="update_project",
            description=(
                "Update a project's section content, properties, headline, or tags. "
                "Supports section-level updates to avoid rewriting the entire file. "
                "At least one of section+content, properties, headline, or tags must be provided. "
                "Always updates :MODIFIED: timestamp automatically. "
                "For format specifications, read emacs-org://guide/project-format."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Project slug, CUSTOM_ID, or title substring",
                    },
                    "section": {
                        "type": "string",
                        "description": "Section name to update (e.g., 'Description', 'Goals', 'Notes')",
                    },
                    "content": {
                        "type": "string",
                        "description": "New content for the section (used with section parameter)",
                    },
                    "properties": {
                        "type": "object",
                        "description": 'Properties to update (e.g., {"STATUS": "active", "REPO": "https://..."})',
                        "additionalProperties": {"type": "string"},
                    },
                    "headline": {
                        "type": "string",
                        "description": "New project headline/title",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'New tags list (e.g., ["project", "infrastructure"])',
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="search_projects",
            description=(
                "Search across all projects by query string. Case-insensitive substring match "
                "on project titles and all section content. Returns matching projects."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (matches titles and content)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="link_task_to_project",
            description=(
                "Add a task link to a project's Related Tasks section. The task_link should be "
                "an org-mode link like '- [[file:~/org/tasks.org::#task-gh-28][GH-28 Task name]]'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_identifier": {
                        "type": "string",
                        "description": "Project slug, CUSTOM_ID, or title substring",
                    },
                    "task_link": {
                        "type": "string",
                        "description": "Org-mode link string for the task",
                    },
                },
                "required": ["project_identifier", "task_link"],
            },
        ),
        Tool(
            name="regenerate_project_index",
            description=(
                "Regenerate ~/org/projects/index.org from all project files. "
                "Call this once after initial setup or if the index becomes out of sync."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="diagnostic_env",
            description="Diagnostic tool to check environment variables for ediff approval",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# =============================================================================
# MCP Tool Handlers
# =============================================================================


###############################################################################
#
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch an MCP tool call to the appropriate handler."""
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
                        arguments["identifier"],
                        arguments.get("section"),
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
                (
                    old_task,
                    new_content,
                    moved,
                    old_section,
                    new_section,
                ) = update_task(
                    arguments["identifier"],
                    arguments["task_entry"],
                )
                output = format_task_update_result(
                    old_task,
                    new_content,
                    moved,
                    old_section,
                    new_section,
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
                        type="text",
                        text=f"Entry '{entry_id}' not found",
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
                    arguments["time"],
                    arguments["headline"],
                    arguments["content"],
                    arguments.get("tags"),
                    arguments.get("existing_time"),
                    arguments.get("existing_headline"),
                )
                output = format_journal_update_result(
                    old_entry, new_entry, result_date
                )
                return [TextContent(type="text", text=output)]

            case "search_journal":
                entries = search_journal(
                    arguments["query"],
                    arguments.get("days_back", 30),
                )
                output = format_search_results(entries, "journal entry")
                return [TextContent(type="text", text=output)]

            # ----- Project Operations -----
            case "list_projects":
                projects = list_projects(arguments.get("status"))
                output = format_project_list(projects)
                return [TextContent(type="text", text=output)]

            case "get_project":
                try:
                    project = get_project(arguments["identifier"])
                except ValueError:
                    return [
                        TextContent(
                            type="text",
                            text=f"Project '{arguments['identifier']}' not found",
                        )
                    ]
                output = format_project_detail(project)
                return [TextContent(type="text", text=output)]

            case "create_project":
                slug, content = create_project(arguments["project_entry"])
                output = format_project_create_result(slug, content)
                return [TextContent(type="text", text=output)]

            case "update_project":
                old_project, new_content = update_project(
                    identifier=arguments["identifier"],
                    section=arguments.get("section"),
                    content=arguments.get("content"),
                    properties=arguments.get("properties"),
                    headline=arguments.get("headline"),
                    tags=arguments.get("tags"),
                )
                output = format_project_update_result(
                    old_project.raw_content,
                    new_content,
                    old_project.slug,
                )
                return [TextContent(type="text", text=output)]

            case "search_projects":
                projects = search_projects(arguments["query"])
                output = format_search_results(projects, "project")
                return [TextContent(type="text", text=output)]

            case "link_task_to_project":
                new_content = link_task_to_project(
                    arguments["project_identifier"],
                    arguments["task_link"],
                )
                return [
                    TextContent(
                        type="text",
                        text=f"Task linked to project successfully.\n\n{new_content}",
                    )
                ]

            case "regenerate_project_index":
                regenerate_project_index()
                config = global_state.config
                index_path = config.projects_dir / "index.org"
                projects = list_projects()
                return [
                    TextContent(
                        type="text",
                        text=f"Project index regenerated at {index_path} ({len(projects)} project(s)).",
                    )
                ]

            case "diagnostic_env":
                # Diagnostic tool to check configuration
                ediff_val_env = os.getenv("EMACS_EDIFF_APPROVAL", "NOT SET")
                emacsclient_val_env = os.getenv("EMACSCLIENT_PATH", "NOT SET")
                emacsclient_found = get_emacsclient_path()
                ediff_enabled = is_ediff_approval_enabled()

                diagnostic = f"""Configuration Diagnostic for Ediff Approval
================================================

Config values (from CLI args / env vars / defaults):
  ediff_approval = {global_state.config.ediff_approval!r}
  emacsclient_path = {global_state.config.emacsclient_path!r}

Environment variables (for debugging):
  EMACS_EDIFF_APPROVAL = {ediff_val_env!r}
  EMACSCLIENT_PATH = {emacsclient_val_env!r}

Runtime checks:
  get_emacsclient_path() = {emacsclient_found}
  is_ediff_approval_enabled() = {ediff_enabled}

All EMACS-related env vars:
{[k for k in os.environ.keys() if "EMACS" in k.upper()]}
"""
                return [TextContent(type="text", text=diagnostic)]

            case _:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except FileNotFoundError as e:
        return [TextContent(type="text", text=f"File not found: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Unexpected error: {type(e).__name__}: {e}",
            )
        ]
