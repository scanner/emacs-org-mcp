"""
Pytest fixtures and factories for testing the MCP server.
"""

from datetime import date
from pathlib import Path
from typing import TypedDict

import pytest
from pytest_mock import MockerFixture

import server

# =============================================================================
# Type Definitions
# =============================================================================


class TasksFileInfo(TypedDict):
    """Metadata returned by sample_tasks_file fixture."""

    path: Path
    active_count: int
    completed_count: int
    task_names: list[str]


class JournalFilesInfo(TypedDict):
    """Metadata returned by sample_journal_files fixture."""

    journal_dir: Path
    today: date
    today_entry_count: int
    today_file: Path


# =============================================================================
# Sample Data Factories
# =============================================================================


def make_task(
    headline: str,
    custom_id: str,
    status: str = "TODO",
    description: str = "",
    task_items: list[tuple[bool, str]] | None = None,
    task_id: str | None = None,
) -> str:
    """
    Factory to create a task entry string.

    Args:
        headline: Task headline (e.g., "JIRA-1234 Fix the bug")
        custom_id: Task custom ID for :CUSTOM_ID: (e.g., "task-jira-1234")
        status: TODO or DONE
        description: Optional description text
        task_items: List of (completed, text) tuples for checklist items
        task_id: Optional UUID for :ID: property

    Returns:
        Org-formatted task string
    """
    lines: list[str] = [f"** {status} {headline}"]

    # Add :PROPERTIES: drawer
    lines.append(":PROPERTIES:")
    if task_id:
        lines.append(f"   :ID:       {task_id}")
    lines.append(f"   :CUSTOM_ID: {custom_id}")
    lines.append(":END:")

    if description:
        lines.append("*** Description")
        lines.append(description)

    if task_items:
        completed = sum(1 for done, _ in task_items if done)
        total = len(task_items)
        lines.append(f"*** Task items [{completed}/{total}]")
        for done, text in task_items:
            marker = "[X]" if done else "[ ]"
            lines.append(f"- {marker} {text}")

    return "\n".join(lines)


def make_tasks_org(
    active_tasks: list[str] | None = None,
    completed_tasks: list[str] | None = None,
    active_section: str | None = None,
    completed_section: str | None = None,
    high_level_section: str | None = None,
    high_level_items: list[tuple[bool, str]] | None = None,
) -> str:
    """
    Factory to create a complete tasks.org file content.

    Args:
        active_tasks: List of task strings for the active section
        completed_tasks: List of task strings for the completed section
        active_section: Section name for active tasks (defaults to server.ACTIVE_SECTION)
        completed_section: Section name for completed tasks (defaults to server.COMPLETED_SECTION)
        high_level_section: Section name for high level tasks (defaults to server.HIGH_LEVEL_SECTION)
        high_level_items: List of (completed, description) tuples for high level checklist

    Returns:
        Complete tasks.org file content
    """
    active_tasks = active_tasks or []
    completed_tasks = completed_tasks or []
    active_section = active_section or server.ACTIVE_SECTION
    completed_section = completed_section or server.COMPLETED_SECTION
    high_level_section = high_level_section or server.HIGH_LEVEL_SECTION
    high_level_items = high_level_items or []

    # Build high level checklist
    completed = sum(1 for done, _ in high_level_items if done)
    total = len(high_level_items)
    progress = f"[{completed}/{total}]" if high_level_items else "[0/0]"

    lines: list[str] = [f"* {high_level_section} {progress}"]
    for done, description in high_level_items:
        marker = "[X]" if done else "[ ]"
        lines.append(f"- {marker} {description}")
    lines.append("")

    lines.append(f"* {active_section}")
    lines.append("")
    for task in active_tasks:
        lines.append(task)
        lines.append("")

    lines.append(f"* {completed_section}")
    lines.append("")
    for task in completed_tasks:
        lines.append(task)
        lines.append("")

    return "\n".join(lines)


def make_journal_entry(
    time: str,
    headline: str,
    content: str = "",
    tags: list[str] | None = None,
) -> str:
    """
    Factory to create a journal entry string.

    Args:
        time: Time in HH:MM format
        headline: Entry headline
        content: Bullet point content
        tags: List of tags (without colons)

    Returns:
        Org-formatted journal entry string
    """
    tags_str = f" :{':'.join(tags)}:" if tags else ""
    lines: list[str] = [f"** {time} {headline}{tags_str}"]
    if content:
        lines.append(content)
    return "\n".join(lines)


def make_journal_file(entries: list[str], file_date: date) -> str:
    """
    Factory to create a complete journal file content.

    Args:
        entries: List of journal entry strings
        file_date: Date for the journal file header

    Returns:
        Complete journal file content
    """
    lines: list[str] = [f"* {file_date.isoformat()}", ""]
    for entry in entries:
        lines.append(entry)
        lines.append("")
    return "\n".join(lines)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_org_dir(tmp_path: Path, mocker: MockerFixture) -> Path:
    """
    Create a temporary org directory structure and patch server module to use it.

    Yields the tmp_path for further customization in tests.
    """
    # Create directory structure
    tasks_file = tmp_path / "tasks.org"
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()

    # Patch the server module's paths
    mocker.patch("server.TASKS_FILE", tasks_file)
    mocker.patch("server.JOURNAL_DIR", journal_dir)

    return tmp_path


@pytest.fixture
def sample_tasks_file(temp_org_dir: Path) -> TasksFileInfo:
    """
    Create a sample tasks.org file with predefined tasks.

    Returns dict with task metadata for assertions.
    """
    tasks_file = temp_org_dir / "tasks.org"

    active_tasks: list[str] = [
        make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="TODO",
            description="There's a bug in the auth flow.",
            task_items=[
                (True, "Identify the issue"),
                (False, "Fix the code"),
                (False, "Add tests"),
            ],
        ),
        make_task(
            headline="Add new feature",
            custom_id="task-new-feature",
            status="TODO",
            description="Implement the new feature.",
            task_items=[(False, "Design"), (False, "Implement")],
        ),
        make_task(
            headline="Review pending",
            custom_id="task-review",
            status="TODO",
            description="Waiting for review.",
        ),
    ]

    completed_tasks: list[str] = [
        make_task(
            headline="JIRA-4321 Old completed task",
            custom_id="task-jira-4321",
            status="DONE",
            description="This was done.",
            task_items=[(True, "All done")],
        ),
    ]

    high_level_items: list[tuple[bool, str]] = [
        (False, "Fix authentication bug"),
        (False, "Add new feature"),
        (False, "Review pending"),
        (True, "Old completed task"),
    ]

    content = make_tasks_org(
        active_tasks, completed_tasks, high_level_items=high_level_items
    )
    tasks_file.write_text(content)

    return {
        "path": tasks_file,
        "active_count": 3,  # All TODO
        "completed_count": 1,
        "task_names": [
            "task-jira-1234",
            "task-new-feature",
            "task-review",
            "task-jira-4321",
        ],
    }


@pytest.fixture
def sample_journal_files(temp_org_dir: Path) -> JournalFilesInfo:
    """
    Create sample journal files for testing.

    Returns dict with journal metadata for assertions.
    """
    journal_dir = temp_org_dir / "journal"
    today = date.today()

    # Today's journal
    today_entries: list[str] = [
        make_journal_entry(
            time="09:00",
            headline="JIRA-1234 Started work on auth bug",
            content="- Identified the root cause\n- Started implementing fix",
        ),
        make_journal_entry(
            time="14:30",
            headline="Team meeting",
            content="- Discussed sprint goals\n- Reviewed PRs",
            tags=["meeting"],
        ),
        make_journal_entry(
            time="17:00",
            headline="End of day summary",
            content="- Completed auth bug investigation\n- PR ready for review",
            tags=["daily_summary"],
        ),
    ]
    today_file = journal_dir / today.strftime("%Y%m%d")
    today_file.write_text(make_journal_file(today_entries, today))

    return {
        "journal_dir": journal_dir,
        "today": today,
        "today_entry_count": 3,
        "today_file": today_file,
    }


@pytest.fixture
def empty_tasks_file(temp_org_dir: Path) -> Path:
    """Create an empty tasks.org file with just the section headers."""
    tasks_file = temp_org_dir / "tasks.org"
    content = make_tasks_org([], [])
    tasks_file.write_text(content)
    return tasks_file


@pytest.fixture
def empty_journal_dir(temp_org_dir: Path) -> Path:
    """Return the empty journal directory."""
    return temp_org_dir / "journal"
