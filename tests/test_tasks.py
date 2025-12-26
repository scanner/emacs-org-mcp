"""Tests for task-related server functions."""

from pathlib import Path

import pytest

import server
from tests.conftest import (
    TasksFileInfo,
    make_task,
)


class TestListTasks:
    """Tests for list_tasks function."""

    def test_list_active_tasks(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test listing tasks from active section."""
        tasks = server.list_tasks(server.ACTIVE_SECTION)

        assert len(tasks) == sample_tasks_file["active_count"]
        assert all(t.section == server.ACTIVE_SECTION for t in tasks)

    def test_list_completed_tasks(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test listing tasks from completed section."""
        tasks = server.list_tasks(server.COMPLETED_SECTION)

        assert len(tasks) == sample_tasks_file["completed_count"]
        assert all(t.section == server.COMPLETED_SECTION for t in tasks)
        assert all(t.status == "DONE" for t in tasks)

    def test_list_empty_section(self, empty_tasks_file: Path) -> None:
        """Test listing tasks from an empty section."""
        tasks = server.list_tasks(server.ACTIVE_SECTION)

        assert len(tasks) == 0

    def test_task_has_expected_fields(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that listed tasks have all expected fields populated."""
        tasks = server.list_tasks(server.ACTIVE_SECTION)

        for task in tasks:
            assert task.custom_id != ""  # All our test tasks have names
            assert task.headline != ""
            assert task.status in ("TODO", "DONE")
            assert task.section == server.ACTIVE_SECTION
            assert task.content != ""


class TestFindTask:
    """Tests for find_task function."""

    def test_find_by_custom_id(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test finding a task by its :CUSTOM_ID: value."""
        result = server.find_task("task-jira-1234")

        assert result is not None
        task, heading, section, org = result
        assert task.custom_id == "task-jira-1234"
        assert "JIRA-1234" in task.headline

    def test_find_by_ticket_id(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test finding a task by JIRA ticket ID in headline."""
        result = server.find_task("JIRA-1234")

        assert result is not None
        task, _, _, _ = result
        assert "JIRA-1234" in task.headline

    def test_find_by_headline_substring(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test finding a task by partial headline match."""
        result = server.find_task("new feature")

        assert result is not None
        task, _, _, _ = result
        assert "new feature" in task.headline.lower()

    def test_find_in_specific_section(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test finding a task in a specific section only."""
        # This task is in Active section
        result = server.find_task(
            "task-jira-1234", section=server.ACTIVE_SECTION
        )
        assert result is not None

        # Should not find it in Completed section
        result = server.find_task(
            "task-jira-1234", section=server.COMPLETED_SECTION
        )
        assert result is None

    def test_find_nonexistent_task(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that finding a nonexistent task returns None."""
        result = server.find_task("task-does-not-exist")

        assert result is None

    def test_find_completed_task(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test finding a task in the completed section."""
        result = server.find_task("task-jira-4321")

        assert result is not None
        task, _, _, _ = result
        assert task.status == "DONE"
        assert task.section == server.COMPLETED_SECTION


class TestCreateTask:
    """Tests for create_task function."""

    def test_create_task_in_active_section(
        self, empty_tasks_file: Path
    ) -> None:
        """Test creating a new task in the Active section."""
        new_task = make_task(
            headline="New task headline",
            custom_id="task-new",
            description="This is a new task",
        )

        result = server.create_task(server.ACTIVE_SECTION, new_task)

        section, content = result
        assert section == server.ACTIVE_SECTION
        assert "New task headline" in content

        # Verify task was added
        tasks = server.list_tasks(server.ACTIVE_SECTION)
        assert len(tasks) == 1
        assert tasks[0].custom_id == "task-new"

    def test_create_task_in_completed_section(
        self, empty_tasks_file: Path
    ) -> None:
        """Test creating a task directly in the Completed section."""
        done_task = make_task(
            headline="Already done",
            custom_id="task-already-done",
            status="DONE",
        )

        server.create_task(server.COMPLETED_SECTION, done_task)

        tasks = server.list_tasks(server.COMPLETED_SECTION)
        assert len(tasks) == 1
        assert tasks[0].status == "DONE"

    def test_create_preserves_existing_tasks(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that creating a task doesn't affect existing tasks."""
        original_count = sample_tasks_file["active_count"]

        new_task = make_task("Another task", "task-another")
        server.create_task(server.ACTIVE_SECTION, new_task)

        tasks = server.list_tasks(server.ACTIVE_SECTION)
        assert len(tasks) == original_count + 1

    def test_create_invalid_section_raises(
        self, empty_tasks_file: Path
    ) -> None:
        """Test that creating in a nonexistent section raises ValueError."""
        new_task = make_task("Task", "task-x")

        with pytest.raises(ValueError, match="Section not found"):
            server.create_task("Nonexistent Section", new_task)


class TestUpdateTask:
    """Tests for update_task function."""

    def test_update_task_content(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test updating a task's content while keeping status."""
        updated_task = make_task(
            headline="JIRA-1234 Updated headline",
            custom_id="task-jira-1234",
            status="TODO",
            description="Updated description",
        )

        result = server.update_task("task-jira-1234", updated_task)

        old_task, new_content, was_moved, old_section, new_section = result
        assert old_task.custom_id == "task-jira-1234"
        assert "Updated headline" in new_content
        assert not was_moved
        assert old_section == new_section == server.ACTIVE_SECTION

        # Verify the update
        found = server.find_task("task-jira-1234")
        assert found is not None
        task, _, _, _ = found
        assert "Updated headline" in task.headline
        assert "Updated description" in task.content

    def test_update_moves_to_completed_on_done(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that updating status to DONE moves task to Completed section."""
        original_active = len(server.list_tasks(server.ACTIVE_SECTION))
        original_completed = len(server.list_tasks(server.COMPLETED_SECTION))

        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        result = server.update_task("task-jira-1234", done_task)
        _, _, was_moved, old_section, new_section = result

        assert was_moved
        assert old_section == server.ACTIVE_SECTION
        assert new_section == server.COMPLETED_SECTION

        # Verify it moved sections
        active = server.list_tasks(server.ACTIVE_SECTION)
        completed = server.list_tasks(server.COMPLETED_SECTION)

        assert len(active) == original_active - 1
        assert len(completed) == original_completed + 1

        # Verify it's findable in completed
        found = server.find_task(
            "task-jira-1234", section=server.COMPLETED_SECTION
        )
        assert found is not None

    def test_update_nonexistent_task_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that updating a nonexistent task raises ValueError."""
        task = make_task("X", "task-x")

        with pytest.raises(ValueError, match="not found"):
            server.update_task("task-nonexistent", task)


class TestMoveTask:
    """Tests for move_task function."""

    def test_move_task_to_completed(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test moving a task from Active to Completed."""
        result = server.move_task(
            "task-jira-1234",
            server.ACTIVE_SECTION,
            server.COMPLETED_SECTION,
        )

        headline, from_section, to_section = result
        assert "JIRA-1234" in headline
        assert from_section == server.ACTIVE_SECTION
        assert to_section == server.COMPLETED_SECTION

        # Verify it's in the new section
        found = server.find_task(
            "task-jira-1234", section=server.COMPLETED_SECTION
        )
        assert found is not None

        # Verify it's not in the old section
        found = server.find_task(
            "task-jira-1234", section=server.ACTIVE_SECTION
        )
        assert found is None

    def test_move_task_to_active(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test moving a task from Completed back to Active."""
        result = server.move_task(
            "task-jira-4321",
            server.COMPLETED_SECTION,
            server.ACTIVE_SECTION,
        )

        headline, from_section, to_section = result
        assert "JIRA-4321" in headline
        assert from_section == server.COMPLETED_SECTION
        assert to_section == server.ACTIVE_SECTION

        found = server.find_task(
            "task-jira-4321", section=server.ACTIVE_SECTION
        )
        assert found is not None

    def test_move_nonexistent_task_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that moving a nonexistent task raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            server.move_task(
                "task-nonexistent",
                server.ACTIVE_SECTION,
                server.COMPLETED_SECTION,
            )

    def test_move_to_invalid_section_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that moving to an invalid section raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            server.move_task(
                "task-jira-1234", server.ACTIVE_SECTION, "Invalid Section"
            )


class TestSearchTasks:
    """Tests for search_tasks function."""

    def test_search_by_headline(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test searching tasks by headline content."""
        results = server.search_tasks("authentication")

        assert len(results) == 1
        assert "authentication" in results[0].headline.lower()

    def test_search_by_ticket_id(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test searching tasks by ticket ID."""
        results = server.search_tasks("JIRA-1234")

        assert len(results) == 1
        assert "JIRA-1234" in results[0].headline

    def test_search_by_content(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test searching tasks by body content."""
        results = server.search_tasks("auth flow")

        assert len(results) >= 1
        # The task with "auth flow" in description should be found
        assert any("auth" in t.content.lower() for t in results)

    def test_search_across_sections(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that search finds tasks in both Active and Completed sections."""
        # Search for something that matches tasks in both sections
        results = server.search_tasks("JIRA")

        # Should find both JIRA-1234 (active) and JIRA-4321 (completed)
        assert len(results) == 2
        sections = {t.section for t in results}
        assert server.ACTIVE_SECTION in sections
        assert server.COMPLETED_SECTION in sections

    def test_search_no_results(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test search with no matching results."""
        results = server.search_tasks("xyzzy-not-found")

        assert len(results) == 0

    def test_search_case_insensitive(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that search is case-insensitive."""
        results_lower = server.search_tasks("authentication")
        results_upper = server.search_tasks("AUTHENTICATION")
        results_mixed = server.search_tasks("Authentication")

        assert len(results_lower) == len(results_upper) == len(results_mixed)


class TestPreviewTaskUpdate:
    """Tests for task preview functionality."""

    def test_preview_shows_diff_without_modifying(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that preview returns diff without changing the file."""
        # Get original task
        original = server.find_task("task-jira-1234")
        assert original is not None
        original_task, _, _, _ = original
        original_content = original_task.content

        # Create updated task content
        updated_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="TODO",
            description="Updated description for preview test.",
            task_items=[
                (True, "Identify the issue"),
                (True, "Fix the code"),  # Changed from False to True
                (False, "Add tests"),
            ],
        )

        # Parse and format preview
        new_heading = server.parse_task_entry(updated_task)
        new_content = server.heading_to_org_string(new_heading)
        preview_output = server.format_task_preview(
            original_task,
            new_content,
            server.ACTIVE_SECTION,
            server.ACTIVE_SECTION,
        )

        # Verify preview output contains diff markers
        assert "Preview:" in preview_output
        assert "Proposed changes:" in preview_output

        # Verify file was NOT modified
        after = server.find_task("task-jira-1234")
        assert after is not None
        after_task, _, _, _ = after
        assert after_task.content == original_content

    def test_preview_shows_section_move(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that preview indicates when task will move sections."""
        original = server.find_task("task-jira-1234")
        assert original is not None
        original_task, _, _, _ = original

        # Create DONE version (would move to Completed)
        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        new_heading = server.parse_task_entry(done_task)
        new_content = server.heading_to_org_string(new_heading)
        preview_output = server.format_task_preview(
            original_task,
            new_content,
            server.ACTIVE_SECTION,
            server.COMPLETED_SECTION,
        )

        # Verify preview shows section movement
        assert server.ACTIVE_SECTION in preview_output
        assert server.COMPLETED_SECTION in preview_output
        assert "→" in preview_output

    def test_preview_no_changes(self, sample_tasks_file: TasksFileInfo) -> None:
        """Test preview when content is identical."""
        original = server.find_task("task-jira-1234")
        assert original is not None
        original_task, _, _, _ = original

        # Preview with same content
        preview_output = server.format_task_preview(
            original_task,
            original_task.content,
            server.ACTIVE_SECTION,
            server.ACTIVE_SECTION,
        )

        # Should indicate no changes
        assert "no changes" in preview_output.lower()


class TestFormatSimpleDiff:
    """Tests for format_simple_diff function."""

    def test_diff_shows_additions(self) -> None:
        """Test that diff shows added lines."""
        old = "line1\nline2"
        new = "line1\nline2\nline3"

        diff = server.format_simple_diff(old, new)

        assert "+ line3" in diff

    def test_diff_shows_deletions(self) -> None:
        """Test that diff shows removed lines."""
        old = "line1\nline2\nline3"
        new = "line1\nline2"

        diff = server.format_simple_diff(old, new)

        assert "− line3" in diff

    def test_diff_shows_replacements(self) -> None:
        """Test that diff shows changed lines."""
        old = "- [ ] Pending item"
        new = "- [X] Pending item"

        diff = server.format_simple_diff(old, new)

        assert "− - [ ] Pending item" in diff
        assert "+ - [X] Pending item" in diff

    def test_diff_no_changes(self) -> None:
        """Test diff when content is identical."""
        content = "line1\nline2"

        diff = server.format_simple_diff(content, content)

        assert "no changes" in diff.lower()


class TestHighLevelTasksChecklist:
    """Tests for High Level Tasks checklist maintenance."""

    def test_create_task_adds_to_high_level_checklist(
        self, empty_tasks_file: Path
    ) -> None:
        """
        Given an empty tasks file
        When a task is created
        Then it should be added to the High Level Tasks checklist
        """
        new_task = make_task(
            headline="GH-123 Implement new feature",
            custom_id="task-gh-123",
        )

        server.create_task(server.ACTIVE_SECTION, new_task)

        # Read the file and verify checklist was updated
        org = server.Org(str(server.TASKS_FILE))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if server.HIGH_LEVEL_SECTION in title:
                    high_level_section = heading
                    break

        assert high_level_section is not None
        assert "- [ ] Implement new feature" in high_level_section.body

    def test_update_task_marks_checklist_done(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a task in the active section
        When the task is marked as DONE
        Then the High Level Tasks checklist should mark it as complete
        """
        # Mark an existing task as done
        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        server.update_task("task-jira-1234", done_task)

        # Read the file and verify checklist was updated
        org = server.Org(str(server.TASKS_FILE))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if server.HIGH_LEVEL_SECTION in title:
                    high_level_section = heading
                    break

        assert high_level_section is not None
        assert "- [X] Fix authentication bug" in high_level_section.body

    def test_high_level_checklist_strips_ticket_id(
        self, empty_tasks_file: Path
    ) -> None:
        """
        Given a task with a ticket ID in the headline
        When the task is created
        Then the High Level Tasks checklist should not include the ticket ID
        """
        new_task = make_task(
            headline="JIRA-456 Refactor payment module",
            custom_id="task-jira-456",
        )

        server.create_task(server.ACTIVE_SECTION, new_task)

        # Read the file and verify checklist strips ticket ID
        org = server.Org(str(server.TASKS_FILE))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if server.HIGH_LEVEL_SECTION in title:
                    high_level_section = heading
                    break

        assert high_level_section is not None
        assert "- [ ] Refactor payment module" in high_level_section.body
        assert "JIRA-456" not in high_level_section.body


class TestUUIDGeneration:
    """Tests for UUID generation when creating tasks."""

    def test_create_task_generates_uuid(self, empty_tasks_file: Path) -> None:
        """
        Given a task entry without a :PROPERTIES: drawer
        When the task is created
        Then a UUID should be generated and added to :PROPERTIES:
        """
        new_task = make_task(
            headline="Task without UUID",
            custom_id="task-no-uuid",
        )

        server.create_task(server.ACTIVE_SECTION, new_task)

        # Verify the task has a UUID
        tasks = server.list_tasks(server.ACTIVE_SECTION)
        assert len(tasks) == 1
        assert tasks[0].id != ""
        assert len(tasks[0].id) == 36  # Standard UUID format
        assert tasks[0].id == tasks[0].id.upper()  # Should be uppercase

    def test_create_task_preserves_existing_uuid(
        self, empty_tasks_file: Path
    ) -> None:
        """
        Given a task entry with an existing :ID: in :PROPERTIES:
        When the task is created
        Then the existing UUID should be preserved
        """
        existing_uuid = "12345678-ABCD-1234-ABCD-123456789012"
        task_with_uuid = f"""** TODO Task with UUID
:PROPERTIES:
   :ID:       {existing_uuid}
   :CUSTOM_ID: task-with-uuid
:END:

*** Description
Task description here.
"""

        server.create_task(server.ACTIVE_SECTION, task_with_uuid)

        # Verify the UUID was preserved
        tasks = server.list_tasks(server.ACTIVE_SECTION)
        assert len(tasks) == 1
        assert tasks[0].id == existing_uuid

    def test_generated_uuid_is_valid(self, empty_tasks_file: Path) -> None:
        """
        Given a new task without UUID
        When the task is created
        Then the generated UUID should be a valid UUID4
        """
        import uuid

        new_task = make_task(
            headline="Another task",
            custom_id="task-another",
        )

        server.create_task(server.ACTIVE_SECTION, new_task)

        tasks = server.list_tasks(server.ACTIVE_SECTION)
        assert len(tasks) == 1

        # Verify it's a valid UUID by parsing it
        try:
            parsed_uuid = uuid.UUID(tasks[0].id)
            assert parsed_uuid.version == 4  # Should be UUID4
        except ValueError:
            pytest.fail(f"Generated ID is not a valid UUID: {tasks[0].id}")


class TestTaskIDExtraction:
    """Tests for :ID: field extraction from :PROPERTIES: drawer."""

    def test_list_tasks_populates_id_field(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given tasks with :PROPERTIES: drawer containing :ID:
        When list_tasks is called
        Then each task should have the id field populated
        """
        # Create a task with an explicit UUID to test
        task_with_id = """** TODO Task with explicit ID
:PROPERTIES:
   :ID:       TEST-UUID-1234-5678-90AB-CDEF12345678
   :CUSTOM_ID: task-with-id
:END:

*** Description
This task has an explicit ID.
"""
        # Add it to the file
        content = server.TASKS_FILE.read_text()
        import re

        content = re.sub(
            rf"(\* {server.ACTIVE_SECTION}\n)",
            rf"\1{task_with_id}\n",
            content,
        )
        server.TASKS_FILE.write_text(content)

        tasks = server.list_tasks(server.ACTIVE_SECTION)

        # Find the task we added
        task_with_explicit_id = next(
            (t for t in tasks if t.custom_id == "task-with-id"), None
        )
        assert task_with_explicit_id is not None
        assert (
            task_with_explicit_id.id == "TEST-UUID-1234-5678-90AB-CDEF12345678"
        )

    def test_find_task_populates_id_field(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a task with :PROPERTIES: drawer containing :ID:
        When find_task is called
        Then the returned task should have the id field populated
        """
        # Create a task with an explicit UUID
        task_with_id = """** TODO Another task with ID
:PROPERTIES:
   :ID:       FIND-UUID-ABCD-1234-5678-90ABCDEF1234
   :CUSTOM_ID: task-find-by-id
:END:

*** Description
Finding this task.
"""
        # Add it to the file
        content = server.TASKS_FILE.read_text()
        import re

        content = re.sub(
            rf"(\* {server.ACTIVE_SECTION}\n)",
            rf"\1{task_with_id}\n",
            content,
        )
        server.TASKS_FILE.write_text(content)

        result = server.find_task("task-find-by-id")

        assert result is not None
        task, _, _, _ = result
        assert task.id == "FIND-UUID-ABCD-1234-5678-90ABCDEF1234"

    def test_tasks_without_id_have_empty_string(
        self, empty_tasks_file: Path
    ) -> None:
        """
        Given a task without :PROPERTIES: drawer
        When the task is parsed
        Then the id field should be an empty string
        """
        # Create a task without properties manually (but with minimal :CUSTOM_ID:)
        task_without_props = """** TODO Simple task
:PROPERTIES:
   :CUSTOM_ID: task-simple
:END:

*** Description
No properties drawer here (no :ID:).
"""

        # Manually add to file
        content = server.TASKS_FILE.read_text()
        import re

        content = re.sub(
            rf"(\* {server.ACTIVE_SECTION}\n)",
            rf"\1{task_without_props}\n",
            content,
        )
        server.TASKS_FILE.write_text(content)

        # Verify the task has empty id
        result = server.find_task("task-simple")
        assert result is not None
        task, _, _, _ = result
        assert task.id == ""
