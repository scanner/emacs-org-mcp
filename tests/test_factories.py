"""Tests for the factory functions - validates they produce parseable org content."""

from datetime import date
from pathlib import Path

from orgmunge import Org
from pytest_mock import MockerFixture

import server
from tests.conftest import (
    make_journal_entry,
    make_journal_file,
    make_task,
    make_tasks_org,
)


class TestMakeTask:
    """Tests that make_task produces valid parseable org content."""

    def test_task_parseable_by_orgmunge(self) -> None:
        """Test that generated task can be parsed by orgmunge."""
        task_str = make_task(
            headline="JIRA-123 Test task",
            custom_id="task-jira-123",
            description="A description",
            task_items=[(True, "Done"), (False, "Pending")],
        )

        # Wrap in a section header for valid org structure
        org_content = f"* Section\n{task_str}\n"
        org = Org(org_content, from_file=False)

        # Find the task heading (level 2)
        task_headings = [
            h for h in org.get_all_headings() if h.headline.level == 2
        ]
        assert len(task_headings) == 1

        task_heading = task_headings[0]
        assert task_heading.headline.todo == "TODO"
        assert "JIRA-123 Test task" in str(task_heading.headline)

    def test_task_custom_id_in_properties(self) -> None:
        """Test that :CUSTOM_ID: appears in the :PROPERTIES: drawer."""
        task_str = make_task(headline="Test", custom_id="task-test-name")
        org_content = f"* Section\n{task_str}\n"
        org = Org(org_content, from_file=False)

        task_headings = [
            h for h in org.get_all_headings() if h.headline.level == 2
        ]
        assert len(task_headings) == 1

        properties = task_headings[0].properties or {}
        assert "CUSTOM_ID" in properties
        assert properties["CUSTOM_ID"] == "task-test-name"


class TestMakeTasksOrg:
    """Tests that make_tasks_org produces valid tasks.org structure."""

    def test_tasks_org_has_both_sections(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """Test that generated tasks.org has Active and Completed sections."""
        tasks_file = tmp_path / "tasks.org"
        mocker.patch.object(server, "TASKS_FILE", tasks_file)

        content = make_tasks_org()
        tasks_file.write_text(content)

        org = server.get_org()
        active = server.find_section(org, server.ACTIVE_SECTION)
        completed = server.find_section(org, server.COMPLETED_SECTION)

        assert active is not None
        assert completed is not None

    def test_tasks_org_with_tasks_parseable(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """Test that tasks.org with tasks can be parsed by server functions."""
        tasks_file = tmp_path / "tasks.org"
        mocker.patch.object(server, "TASKS_FILE", tasks_file)

        task1 = make_task(headline="Task One", custom_id="task-one")
        task2 = make_task(
            headline="Task Two", custom_id="task-two", status="DONE"
        )
        content = make_tasks_org(active_tasks=[task1], completed_tasks=[task2])
        tasks_file.write_text(content)

        active_tasks = server.list_tasks(server.ACTIVE_SECTION)
        completed_tasks = server.list_tasks(server.COMPLETED_SECTION)

        assert len(active_tasks) == 1
        assert active_tasks[0].custom_id == "task-one"
        assert active_tasks[0].status == "TODO"

        assert len(completed_tasks) == 1
        assert completed_tasks[0].custom_id == "task-two"
        assert completed_tasks[0].status == "DONE"


class TestMakeJournalEntry:
    """Tests that make_journal_entry produces valid journal entry format."""

    def test_entry_parseable_by_server(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """Test that journal entry can be parsed by server's parse function."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        mocker.patch.object(server, "JOURNAL_DIR", journal_dir)

        entry = make_journal_entry(
            time="14:30",
            headline="JIRA-456 Test entry",
            content="- Bullet one\n- Bullet two",
            tags=["daily_summary"],
        )
        journal_content = make_journal_file([entry], date(2025, 1, 15))

        journal_file = journal_dir / "20250115"
        journal_file.write_text(journal_content)

        entries = server.parse_journal_entries(journal_file)

        assert len(entries) == 1
        assert entries[0].time == "14:30"
        assert "JIRA-456 Test entry" in entries[0].headline
        assert "daily_summary" in entries[0].tags
        assert "Bullet one" in entries[0].content


class TestMakeJournalFile:
    """Tests that make_journal_file produces valid journal file format."""

    def test_journal_file_header(self) -> None:
        """Test that journal file has correct date header format."""
        content = make_journal_file([], date(2025, 12, 22))
        lines = content.split("\n")

        # First line should be the date header
        assert lines[0] == "* 2025-12-22"

    def test_journal_file_multiple_entries(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """Test parsing journal file with multiple entries."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        mocker.patch.object(server, "JOURNAL_DIR", journal_dir)

        entries = [
            make_journal_entry("09:00", "Morning standup"),
            make_journal_entry("12:00", "Lunch break", tags=["break"]),
            make_journal_entry(
                "17:00",
                "EOD summary",
                content="- Did stuff",
                tags=["daily_summary"],
            ),
        ]
        content = make_journal_file(entries, date(2025, 6, 15))

        journal_file = journal_dir / "20250615"
        journal_file.write_text(content)

        parsed = server.parse_journal_entries(journal_file)

        assert len(parsed) == 3
        assert parsed[0].time == "09:00"
        assert parsed[1].time == "12:00"
        assert parsed[2].time == "17:00"
        assert "break" in parsed[1].tags
        assert "daily_summary" in parsed[2].tags
