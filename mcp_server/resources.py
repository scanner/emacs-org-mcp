"""
MCP resource definitions and handlers.
"""

# system imports
import json
import pathlib
from datetime import date

# 3rd party imports
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource
from pydantic import AnyUrl

# project imports
from mcp_server.config import global_state, server
from mcp_server.journal import (
    get_journal_path,
    journal_entry_to_dict,
    parse_journal_entries,
)
from mcp_server.projects import (
    list_projects,
    project_to_dict,
)
from mcp_server.tasks import (
    list_tasks,
    task_to_dict,
)

# =============================================================================
# Resource Content Loaders
# =============================================================================


def load_guide(filename: str) -> str:
    """Load a guide file from the resources/guides directory."""
    guide_path = (
        pathlib.Path(__file__).parent.parent / "resources" / "guides" / filename
    )
    return guide_path.read_text()


def get_task_format_guide() -> str:
    """Return comprehensive task format documentation."""
    return load_guide("task-format.md")


def get_journal_format_guide() -> str:
    """Return comprehensive journal format documentation."""
    return load_guide("journal-format.md")


def get_project_format_guide() -> str:
    """Return comprehensive project format documentation."""
    return load_guide("project-format.md")


# =============================================================================
# Resources
# =============================================================================


###############################################################################
#
@server.list_resources()
async def list_resources() -> list[Resource]:
    """
    List available MCP resources.

    URI scheme conventions:
      - ``org://`` — Live data from org files (tasks, journal entries,
        project index). Content changes as the underlying files change.
      - ``emacs-org://`` — Static documentation (format guides, usage
        instructions). Content is bundled with the server and does not
        change at runtime.
    """
    return [
        # org:// — live data resources
        Resource(
            uri=AnyUrl("org://tasks/active"),
            name="Active Tasks",
            description="Tasks in the Active Task List",
        ),
        Resource(
            uri=AnyUrl("org://tasks/completed"),
            name="Completed Tasks",
            description="Tasks in the Completed Task List",
        ),
        Resource(
            uri=AnyUrl("org://journal/today"),
            name="Today's Journal",
            description="Journal entries for today",
        ),
        # emacs-org:// — static documentation resources
        Resource(
            uri=AnyUrl("emacs-org://guide/task-format"),
            name="Task Format Guide",
            description="Complete specification for task format and properties",
            mimeType="text/markdown",
        ),
        Resource(
            uri=AnyUrl("emacs-org://guide/journal-format"),
            name="Journal Format Guide",
            description="Complete specification for journal entry format",
            mimeType="text/markdown",
        ),
        Resource(
            uri=AnyUrl("emacs-org://guide/project-format"),
            name="Project Format Guide",
            description="Complete specification for project format and management",
            mimeType="text/markdown",
        ),
        Resource(
            uri=AnyUrl("org://projects/index"),
            name="Project Index",
            description="Index of all projects with status and descriptions",
        ),
    ]


###############################################################################
#
@server.read_resource()
async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
    """Return the content for a single MCP resource identified by URI."""
    uri_str = str(uri)
    match uri_str:
        case "org://tasks/active":
            tasks = list_tasks(global_state.config.active_section)
            content = json.dumps([task_to_dict(t) for t in tasks], indent=2)
            return [
                ReadResourceContents(
                    content=content, mime_type="application/json"
                )
            ]
        case "org://tasks/completed":
            tasks = list_tasks(global_state.config.completed_section)
            content = json.dumps([task_to_dict(t) for t in tasks], indent=2)
            return [
                ReadResourceContents(
                    content=content, mime_type="application/json"
                )
            ]
        case "org://journal/today":
            entries = parse_journal_entries(get_journal_path(date.today()))
            content = json.dumps(
                [journal_entry_to_dict(e) for e in entries], indent=2
            )
            return [
                ReadResourceContents(
                    content=content, mime_type="application/json"
                )
            ]
        case "emacs-org://guide/task-format":
            content = get_task_format_guide()
            return [
                ReadResourceContents(content=content, mime_type="text/markdown")
            ]
        case "emacs-org://guide/journal-format":
            content = get_journal_format_guide()
            return [
                ReadResourceContents(content=content, mime_type="text/markdown")
            ]
        case "emacs-org://guide/project-format":
            content = get_project_format_guide()
            return [
                ReadResourceContents(content=content, mime_type="text/markdown")
            ]
        case "org://projects/index":
            projects = list_projects()
            content = json.dumps(
                [project_to_dict(p) for p in projects], indent=2
            )
            return [
                ReadResourceContents(
                    content=content, mime_type="application/json"
                )
            ]
        case _:
            raise ValueError(f"Unknown resource: {uri_str}")
