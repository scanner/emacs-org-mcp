"""Tests for task-related server functions."""

import re
import uuid
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
        tasks = server.list_tasks("Tasks")

        assert len(tasks) == sample_tasks_file["active_count"]
        assert all(t.section == "Tasks" for t in tasks)

    def test_list_completed_tasks(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test listing tasks from completed section."""
        tasks = server.list_tasks("Completed Tasks")

        assert len(tasks) == sample_tasks_file["completed_count"]
        assert all(t.section == "Completed Tasks" for t in tasks)
        assert all(t.status == "DONE" for t in tasks)

    def test_list_empty_section(self, empty_tasks_file: Path) -> None:
        """Test listing tasks from an empty section."""
        tasks = server.list_tasks("Tasks")

        assert len(tasks) == 0

    def test_task_has_expected_fields(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that listed tasks have all expected fields populated."""
        tasks = server.list_tasks("Tasks")

        for task in tasks:
            assert task.custom_id != ""  # All our test tasks have names
            assert task.headline != ""
            assert task.status in ("TODO", "DONE")
            assert task.section == "Tasks"
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
        #
        result = server.find_task("task-jira-1234", section="Tasks")
        assert result is not None

        # Should not find it in Completed section
        #
        with pytest.raises(ValueError, match="Could not find task"):
            result = server.find_task(
                "task-jira-1234", section="Completed Tasks"
            )

    def test_find_nonexistent_task(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that finding a nonexistent task returns None."""
        with pytest.raises(ValueError, match="Could not find task"):
            server.find_task("task-does-not-exist")

    def test_find_completed_task(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test finding a task in the completed section."""
        result = server.find_task("task-jira-4321")

        assert result is not None
        task, _, _, _ = result
        assert task.status == "DONE"
        assert task.section == "Completed Tasks"


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

        result = server.create_task("Tasks", new_task)

        section, content = result
        assert section == "Tasks"
        assert "New task headline" in content

        # Verify task was added
        tasks = server.list_tasks("Tasks")
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

        server.create_task("Completed Tasks", done_task)

        tasks = server.list_tasks("Completed Tasks")
        assert len(tasks) == 1
        assert tasks[0].status == "DONE"

    def test_create_preserves_existing_tasks(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that creating a task doesn't affect existing tasks."""
        original_count = sample_tasks_file["active_count"]

        new_task = make_task("Another task", "task-another")
        server.create_task("Tasks", new_task)

        tasks = server.list_tasks("Tasks")
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
        assert old_section == new_section == "Tasks"

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
        original_active = len(server.list_tasks("Tasks"))
        original_completed = len(server.list_tasks("Completed Tasks"))

        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        result = server.update_task("task-jira-1234", done_task)
        _, _, was_moved, old_section, new_section = result

        assert was_moved
        assert old_section == "Tasks"
        assert new_section == "Completed Tasks"

        # Verify it moved sections
        active = server.list_tasks("Tasks")
        completed = server.list_tasks("Completed Tasks")

        assert len(active) == original_active - 1
        assert len(completed) == original_completed + 1

        # Verify it's findable in completed
        found = server.find_task("task-jira-1234", section="Completed Tasks")
        assert found is not None

    def test_update_nonexistent_task_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that updating a nonexistent task raises ValueError."""
        task = make_task("X", "task-x")

        with pytest.raises(ValueError, match="Could not find"):
            server.update_task("task-nonexistent", task)


class TestMoveTask:
    """Tests for move_task function."""

    def test_move_task_to_completed(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test moving a task from Active to Completed."""
        result = server.move_task(
            "task-jira-1234",
            "Tasks",
            "Completed Tasks",
        )

        headline, from_section, to_section = result
        assert "JIRA-1234" in headline
        assert from_section == "Tasks"
        assert to_section == "Completed Tasks"

        # Verify it's in the new section
        found = server.find_task("task-jira-1234", section="Completed Tasks")
        assert found is not None

        # Verify it's not in the old section
        with pytest.raises(ValueError, match="Could not find"):
            found = server.find_task("task-jira-1234", section="Tasks")

    def test_move_task_to_active(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test moving a task from Completed back to Active."""
        result = server.move_task(
            "task-jira-4321",
            "Completed Tasks",
            "Tasks",
        )

        headline, from_section, to_section = result
        assert "JIRA-4321" in headline
        assert from_section == "Completed Tasks"
        assert to_section == "Tasks"

        found = server.find_task("task-jira-4321", section="Tasks")
        assert found is not None

    def test_move_task_without_properties_drawer(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Test moving a task from Completed to Active when it has no :PROPERTIES: drawer.

        This edge case can occur with older tasks or manually created tasks.
        """
        # Create a task without a :PROPERTIES: drawer by directly adding it to the file
        task_without_props = """** DONE Task without properties

*** Description
This task has no properties drawer at all.
"""
        # Add it to the Completed section
        content = server.global_state.config.tasks_file.read_text()
        content = re.sub(
            rf"(\* {"Completed Tasks"}\n)",
            rf"\1{task_without_props}\n",
            content,
        )
        server.global_state.config.tasks_file.write_text(content)

        # Move the task to Active section - should not raise an error
        result = server.move_task(
            "Task without properties",  # Find by headline
            "Completed Tasks",
            "Tasks",
        )

        headline, from_section, to_section = result
        assert "Task without properties" in headline
        assert from_section == "Completed Tasks"
        assert to_section == "Tasks"

        # Verify it's in the Active section now
        found = server.find_task("Task without properties", section="Tasks")
        assert found is not None
        task, _, _, _ = found
        # Task should still have no custom_id since it had no properties
        assert task.custom_id is None or task.custom_id == ""

    def test_move_task_missing_closed_property(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Test moving a task from Completed to Active when it's missing :CLOSED: property.

        This can happen if a task was manually marked DONE without using org-mode's
        proper commands, or if it was created before CLOSED tracking was implemented.
        """
        # Create a DONE task with :PROPERTIES: but no :CLOSED:
        task_no_closed = """** DONE Task missing CLOSED property
:PROPERTIES:
   :CUSTOM_ID: task-no-closed
:END:

*** Description
This task is DONE but has no CLOSED timestamp.
"""
        # Add it to the Completed section
        content = server.global_state.config.tasks_file.read_text()
        content = re.sub(
            rf"(\* {"Completed Tasks"}\n)",
            rf"\1{task_no_closed}\n",
            content,
        )
        server.global_state.config.tasks_file.write_text(content)

        # Move the task to Active section - should not raise an error
        result = server.move_task(
            "task-no-closed",
            "Completed Tasks",
            "Tasks",
        )

        headline, from_section, to_section = result
        assert "Task missing CLOSED property" in headline
        assert from_section == "Completed Tasks"
        assert to_section == "Tasks"

        # Verify it's in the Active section now
        found = server.find_task("task-no-closed", section="Tasks")
        assert found is not None
        task, _, _, _ = found
        assert task.custom_id == "task-no-closed"
        # Note: move_task doesn't clear :CLOSED:, so if it didn't have one, it still won't
        assert task.closed is None or task.closed == ""

    def test_move_nonexistent_task_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that moving a nonexistent task raises ValueError."""
        with pytest.raises(ValueError, match="Could not find"):
            server.move_task(
                "task-nonexistent",
                "Tasks",
                "Completed Tasks",
            )

    def test_move_to_invalid_section_raises(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """Test that moving to an invalid section raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            server.move_task("task-jira-1234", "Tasks", "Invalid Section")


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
        assert "Tasks" in sections
        assert "Completed Tasks" in sections

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

        server.create_task("Tasks", new_task)

        # Read the file and verify checklist was updated
        org = server.Org(str(server.global_state.config.tasks_file))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if "High Level Tasks (in order)" in title:
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
        org = server.Org(str(server.global_state.config.tasks_file))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if "High Level Tasks (in order)" in title:
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

        server.create_task("Tasks", new_task)

        # Read the file and verify checklist strips ticket ID
        org = server.Org(str(server.global_state.config.tasks_file))
        high_level_section = None
        for heading in org.get_all_headings():
            if heading.headline.level == 1:
                title = (
                    heading.headline.title
                    if hasattr(heading.headline, "title")
                    else str(heading.headline)
                )
                if "High Level Tasks (in order)" in title:
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

        server.create_task("Tasks", new_task)

        # Verify the task has a UUID
        tasks = server.list_tasks("Tasks")
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

        server.create_task("Tasks", task_with_uuid)

        # Verify the UUID was preserved
        tasks = server.list_tasks("Tasks")
        assert len(tasks) == 1
        assert tasks[0].id == existing_uuid

    def test_generated_uuid_is_valid(self, empty_tasks_file: Path) -> None:
        """
        Given a new task without UUID
        When the task is created
        Then the generated UUID should be a valid UUID4
        """

        new_task = make_task(
            headline="Another task",
            custom_id="task-another",
        )

        server.create_task("Tasks", new_task)

        tasks = server.list_tasks("Tasks")
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
        content = server.global_state.config.tasks_file.read_text()

        content = re.sub(
            rf"(\* {"Tasks"}\n)",
            rf"\1{task_with_id}\n",
            content,
        )
        server.global_state.config.tasks_file.write_text(content)

        tasks = server.list_tasks("Tasks")

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
        content = server.global_state.config.tasks_file.read_text()

        content = re.sub(
            rf"(\* {"Tasks"}\n)",
            rf"\1{task_with_id}\n",
            content,
        )
        server.global_state.config.tasks_file.write_text(content)

        result = server.find_task("task-find-by-id")

        assert result is not None
        task, _, _, _ = result
        assert task.id == "FIND-UUID-ABCD-1234-5678-90ABCDEF1234"


class TestTaskTimestamps:
    """Tests for task timestamp properties (CREATED, MODIFIED, CLOSED)."""

    def test_create_task_sets_created_timestamp(
        self, empty_tasks_file: Path
    ) -> None:
        """
        Given a new task
        When the task is created
        Then :CREATED: timestamp should be set with active timestamp format
        """
        new_task = make_task(
            headline="New task",
            custom_id="task-new",
        )

        server.create_task("Tasks", new_task)

        # Verify the task has :CREATED: timestamp
        tasks = server.list_tasks("Tasks")
        assert len(tasks) == 1
        assert tasks[0].created != ""
        # Active timestamp format: <YYYY-MM-DD DDD HH:MM>
        assert tasks[0].created.startswith("<")
        assert tasks[0].created.endswith(">")

    def test_update_task_sets_modified_timestamp(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given an existing task
        When the task is updated
        Then :MODIFIED: timestamp should be set with inactive timestamp format
        """
        updated_task = make_task(
            headline="JIRA-1234 Updated headline",
            custom_id="task-jira-1234",
            status="TODO",
        )

        server.update_task("task-jira-1234", updated_task)

        # Verify the task has :MODIFIED: timestamp
        result = server.find_task("task-jira-1234")
        assert result is not None
        task, _, _, _ = result
        assert task.modified != ""
        # Inactive timestamp format: [YYYY-MM-DD DDD HH:MM]
        assert task.modified.startswith("[")
        assert task.modified.endswith("]")

    def test_update_task_to_done_sets_closed_timestamp(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a task with status TODO
        When the task is updated to status DONE
        Then :CLOSED: timestamp should be set with active timestamp format
        """
        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        server.update_task("task-jira-1234", done_task)

        # Verify the task has :CLOSED: timestamp
        result = server.find_task("task-jira-1234")
        assert result is not None
        task, _, _, _ = result
        assert task.closed != ""
        # Active timestamp format: <YYYY-MM-DD DDD HH:MM>
        assert task.closed.startswith("<")
        assert task.closed.endswith(">")

    def test_reopen_task_clears_closed_timestamp(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a task with status TODO
        When the task is marked DONE then reopened to TODO
        Then :CLOSED: timestamp should be cleared
        """
        # First mark a TODO task as done (use task-jira-1234 which starts as TODO)
        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )
        server.update_task("task-jira-1234", done_task)

        # Verify it has :CLOSED:
        #
        result = server.find_task("task-jira-1234")
        assert result is not None
        task, _, _, _ = result
        assert task.closed is not None

        # Now reopen it
        #
        reopened_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="TODO",
        )
        server.update_task("task-jira-1234", reopened_task)

        # Verify :CLOSED: was cleared
        #
        result = server.find_task("task-jira-1234")
        assert result is not None
        task, _, _, _ = result

        # And the task.close == None
        #
        assert task.closed is None

    def test_update_done_task_sets_modified_but_not_closed(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a task transitioning from TODO to DONE
        When the task is later updated (but stays DONE)
        Then :MODIFIED: should be updated but :CLOSED: should be preserved
        """
        # First mark a TODO task as done (use task-new-feature which starts as TODO)
        done_task = make_task(
            headline="Implement new feature",
            custom_id="task-new-feature",
            status="DONE",
        )
        server.update_task("task-new-feature", done_task)

        # Get the original :CLOSED: timestamp
        result = server.find_task("task-new-feature")
        assert result is not None
        task, _, _, _ = result
        original_closed = task.closed
        assert original_closed != ""

        # Update the task content (but keep it DONE)
        updated_done_task = make_task(
            headline="Implement new feature - updated description",
            custom_id="task-new-feature",
            status="DONE",
        )
        server.update_task("task-new-feature", updated_done_task)

        # Verify :MODIFIED: was set but :CLOSED: was preserved
        result = server.find_task("task-new-feature")
        assert result is not None
        task, _, _, _ = result
        assert task.modified != ""
        # :CLOSED: should be preserved when task stays DONE
        assert task.closed == original_closed

    def test_reopen_done_task_without_closed_property(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        Given a DONE task that has no :CLOSED: property
        When the task is reopened to TODO status
        Then it should not raise an error (gracefully handle missing :CLOSED:)

        This edge case can occur with manually created tasks or tasks
        created before CLOSED tracking was implemented.
        """
        # Create a DONE task without :CLOSED: property by directly adding to file
        task_done_no_closed = """** DONE Task done without closed
:PROPERTIES:
   :CUSTOM_ID: task-done-no-closed
:END:

*** Description
This task is DONE but has no CLOSED timestamp.
"""
        # Add it to the Active section
        content = server.global_state.config.tasks_file.read_text()
        content = re.sub(
            rf"(\* {"Tasks"}\n)",
            rf"\1{task_done_no_closed}\n",
            content,
        )
        server.global_state.config.tasks_file.write_text(content)

        # Verify the task exists and has no :CLOSED:
        result = server.find_task("task-done-no-closed")
        assert result is not None
        task, _, _, _ = result
        assert task.status == "DONE"
        assert task.closed is None or task.closed == ""

        # Now reopen it to TODO - should not raise an error
        reopened_task = make_task(
            headline="Task done without closed",
            custom_id="task-done-no-closed",
            status="TODO",
        )
        server.update_task("task-done-no-closed", reopened_task)

        # Verify it's now TODO and still has no :CLOSED:
        result = server.find_task("task-done-no-closed")
        assert result is not None
        task, _, _, _ = result
        assert task.status == "TODO"
        assert task.closed is None or task.closed == ""
        # Should have :MODIFIED: timestamp
        assert task.modified != ""
