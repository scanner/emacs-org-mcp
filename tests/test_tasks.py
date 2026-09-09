#!/usr/bin/env python
#
"""
Tests for reading, writing and filing the tasks in tasks.org.

These are the promises the task tools make about one file: a task can be
named the several ways a person remembers it, an edit replaces the content
without disturbing the bookkeeping, and finishing or reopening one files it
with its peers and stamps when it happened.
"""

import uuid
from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.config import global_state
from mcp_server.tasks import (
    create_task,
    find_task,
    heading_to_org_string,
    list_tasks,
    move_task,
    parse_task_entry,
    search_tasks,
    update_task,
)
from mcp_server.utils import format_simple_diff
from tests.conftest import (
    TasksFileInfo,
    make_task,
    make_tasks_org,
)


class TestListTasks:
    """Reading a section back out of the file."""

    @pytest.mark.parametrize(
        "section, status",
        [
            pytest.param("Tasks", "TODO", id="active"),
            pytest.param("Completed Tasks", "DONE", id="completed"),
        ],
    )
    def test_a_section_lists_its_own_tasks_in_full(
        self, sample_tasks_file: TasksFileInfo, section: str, status: str
    ):
        """
        GIVEN: A tasks.org with tasks filed in both sections
         WHEN: One section is listed
         THEN: Every task in it comes back and none from the other, since a
               section is what separates work in hand from work finished
          AND: Each task arrives with the fields a caller addresses it by
               populated, not as a headline alone
        """
        expected = {
            "Tasks": sample_tasks_file["active_count"],
            "Completed Tasks": sample_tasks_file["completed_count"],
        }
        tasks = list_tasks(section)

        with check:
            assert len(tasks) == expected[section]
        with check:
            assert {task.section for task in tasks} == {section}
        with check:
            assert {task.status for task in tasks} == {status}

        for task in tasks:
            with check:
                assert task.custom_id and task.headline and task.content, (
                    f"{task.headline} came back only partly populated"
                )

    def test_an_empty_section_lists_nothing_rather_than_failing(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A tasks.org whose sections exist but hold no tasks
         WHEN: One is listed
         THEN: It comes back empty, because a section with nothing in it is
               an ordinary state and not a missing section
        """
        assert list_tasks("Tasks") == []


class TestFindTask:
    """Naming one task out of the file."""

    @pytest.mark.parametrize(
        "identifier",
        ["task-jira-1234", "JIRA-1234", "authentication"],
        ids=["custom-id", "ticket", "headline-substring"],
    )
    def test_a_task_answers_to_any_of_the_things_that_name_it(
        self, sample_tasks_file: TasksFileInfo, identifier: str
    ):
        """
        GIVEN: A task carrying a :CUSTOM_ID:, a ticket in its headline, and
               words a person would remember it by
         WHEN: It is looked up by any one of them
         THEN: The same task comes back, so a caller can name it the way they
               happen to have it rather than looking the id up first
        """
        task, _, _, _ = find_task(identifier)

        assert task.custom_id == "task-jira-1234"

    def test_a_task_is_found_wherever_it_is_filed(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: A task in the completed section
         WHEN: It is looked up without naming a section
         THEN: It is found, and reports the section it is actually in --
               finishing a task must not make it unaddressable
        """
        task, _, _, _ = find_task("task-jira-4321")

        with check:
            assert task.status == "DONE"
        with check:
            assert task.section == "Completed Tasks"

    def test_naming_a_section_looks_only_there(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: A task in the active section
         WHEN: It is looked up with the search restricted to the completed
               section
         THEN: It is not found, since a caller who named a section is asking
               about that section and not for the nearest match anywhere
        """
        find_task("task-jira-1234", section="Tasks")

        with pytest.raises(ValueError, match="Could not find task"):
            find_task("task-jira-1234", section="Completed Tasks")

    def test_a_task_that_is_not_there_is_reported_as_missing(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: An identifier matching no task
         WHEN: It is looked up
         THEN: It raises rather than returning nothing, so a caller cannot
               carry on and write against a task that does not exist
        """
        with pytest.raises(ValueError, match="Could not find task"):
            find_task("task-does-not-exist")


class TestCreateTask:
    """Adding a task to the file."""

    @pytest.mark.parametrize(
        "section, status",
        [
            pytest.param("Tasks", "TODO", id="active"),
            pytest.param("Completed Tasks", "DONE", id="completed"),
        ],
    )
    def test_a_task_is_filed_in_the_section_it_was_addressed_to(
        self, empty_tasks_file: Path, section: str, status: str
    ):
        """
        GIVEN: A task entry and the section it belongs in
         WHEN: It is created
         THEN: It lands in that section and is addressable there

        Creating straight into the completed section is not a curiosity: it
        is how work already finished gets recorded after the fact.
        """
        returned_section, content = create_task(
            section, make_task("New task headline", "task-new", status=status)
        )

        (task,) = list_tasks(section)

        with check:
            assert returned_section == section
        with check:
            assert "New task headline" in content
        with check:
            assert task.custom_id == "task-new"
        with check:
            assert task.status == status

    def test_creating_a_task_leaves_the_others_alone(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: A tasks.org already holding tasks
         WHEN: Another is created
         THEN: The section holds exactly one more than it did -- the write
               rewrites the whole file, so the tasks already in it are as
               exposed as the one being added
        """
        before = {task.custom_id for task in list_tasks("Tasks")}

        create_task("Tasks", make_task("Another task", "task-another"))

        assert {task.custom_id for task in list_tasks("Tasks")} == (
            before | {"task-another"}
        )

    def test_creating_into_a_section_that_does_not_exist_is_refused(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A section name matching no heading in the file
         WHEN: A task is created into it
         THEN: It is refused, rather than the section being invented or the
               task filed somewhere the caller did not ask for
        """
        with pytest.raises(ValueError, match="Section not found"):
            create_task("Nonexistent Section", make_task("Task", "task-x"))


class TestUpdateTask:
    """Replacing a task's content, and what that does to where it is filed."""

    def test_an_edit_that_does_not_finish_a_task_leaves_it_where_it_is(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: An active task and a replacement for it that is still TODO
         WHEN: It is updated
         THEN: The new content is in place and the task has not moved, since
               editing a task says nothing about whether it is finished
        """
        updated_task = make_task(
            headline="JIRA-1234 Updated headline",
            custom_id="task-jira-1234",
            status="TODO",
            description="Updated description",
        )

        result = update_task("task-jira-1234", updated_task)

        old_task, new_content, was_moved, old_section, new_section = result
        assert old_task.custom_id == "task-jira-1234"
        assert "Updated headline" in new_content
        assert not was_moved
        assert old_section == new_section == "Tasks"

        # Verify the update
        found = find_task("task-jira-1234")
        assert found is not None
        task, _, _, _ = found
        assert "Updated headline" in task.headline
        assert "Updated description" in task.content

    def test_marking_a_task_done_files_it_with_the_finished_work(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: An active task and a replacement marking it DONE
         WHEN: It is updated
         THEN: It moves to the completed section and is gone from the active
               one, so the active list stays a list of what is still to do
               without anyone having to move it by hand
        """
        original_active = len(list_tasks("Tasks"))
        original_completed = len(list_tasks("Completed Tasks"))

        done_task = make_task(
            headline="JIRA-1234 Fix authentication bug",
            custom_id="task-jira-1234",
            status="DONE",
        )

        result = update_task("task-jira-1234", done_task)
        _, _, was_moved, old_section, new_section = result

        assert was_moved
        assert old_section == "Tasks"
        assert new_section == "Completed Tasks"

        # Verify it moved sections
        active = list_tasks("Tasks")
        completed = list_tasks("Completed Tasks")

        assert len(active) == original_active - 1
        assert len(completed) == original_completed + 1

        # Verify it's findable in completed
        found = find_task("task-jira-1234", section="Completed Tasks")
        assert found is not None

    def test_updating_a_task_that_is_not_there_is_refused(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: An identifier matching no task
         WHEN: An update is submitted for it
         THEN: It is refused rather than creating the task, which would file
               a caller's correction as new work
        """
        task = make_task("X", "task-x")

        with pytest.raises(ValueError, match="Could not find"):
            update_task("task-nonexistent", task)


class TestMoveTask:
    """Filing a task under the other section."""

    @pytest.mark.parametrize(
        "identifier, source, destination",
        [
            pytest.param(
                "task-jira-1234", "Tasks", "Completed Tasks", id="finishing"
            ),
            pytest.param(
                "task-jira-4321", "Completed Tasks", "Tasks", id="reopening"
            ),
        ],
    )
    def test_a_task_moves_and_leaves_nothing_behind(
        self,
        sample_tasks_file: TasksFileInfo,
        identifier: str,
        source: str,
        destination: str,
    ):
        """
        GIVEN: A task filed in one section
         WHEN: It is moved to the other
         THEN: It is findable in the section it went to and gone from the one
               it left -- a move that copies leaves the same task in two
               sections, where a later edit reaches only one of them
          AND: Both directions work, since reopening finished work is as
               ordinary as finishing it
        """
        headline, from_section, to_section = move_task(
            identifier, source, destination
        )

        with check:
            assert (from_section, to_section) == (source, destination)
        with check:
            assert find_task(identifier, section=destination)
        with check:
            assert headline
        with pytest.raises(ValueError, match="Could not find"):
            find_task(identifier, section=source)

    @pytest.mark.parametrize(
        "entry, identifier, missing",
        [
            pytest.param(
                "** DONE Task without properties\n"
                "\n"
                "*** Description\n"
                "This task has no properties drawer at all.\n",
                "Task without properties",
                "custom_id",
                id="no-drawer-at-all",
            ),
            pytest.param(
                "** DONE Task missing CLOSED property\n"
                ":PROPERTIES:\n"
                "   :CUSTOM_ID: task-no-closed\n"
                ":END:\n"
                "\n"
                "*** Description\n"
                "This task is DONE but has no CLOSED timestamp.\n",
                "task-no-closed",
                "closed",
                id="no-closed-timestamp",
            ),
        ],
    )
    def test_a_task_written_before_the_conventions_still_moves(
        self, temp_org_dir: Path, entry: str, identifier: str, missing: str
    ):
        """
        GIVEN: A finished task lacking a property the server would have
               written -- no drawer at all, or a drawer with no :CLOSED: --
               as a hand-written or long-lived task has
         WHEN: It is moved back to the active section
         THEN: The move succeeds, because a property this server adds is not
               something it may require of a file it did not write
          AND: The absent property still reads as absent afterwards, so the
               move does not invent a value to fill it in
        """
        (temp_org_dir / "tasks.org").write_text(make_tasks_org([], [entry]))

        _, from_section, to_section = move_task(
            identifier, "Completed Tasks", "Tasks"
        )
        task, _, _, _ = find_task(identifier, section="Tasks")

        with check:
            assert (from_section, to_section) == ("Completed Tasks", "Tasks")
        with check:
            assert getattr(task, missing) == ""

    @pytest.mark.parametrize(
        "identifier, destination, message",
        [
            pytest.param(
                "task-nonexistent",
                "Completed Tasks",
                "Could not find",
                id="no-such-task",
            ),
            pytest.param(
                "task-jira-1234",
                "Invalid Section",
                "not found",
                id="no-such-section",
            ),
        ],
    )
    def test_a_move_that_cannot_be_made_is_refused_by_name(
        self,
        sample_tasks_file: TasksFileInfo,
        identifier: str,
        destination: str,
        message: str,
    ):
        """
        GIVEN: A move naming a task that does not exist, or a section that
               does not
         WHEN: It is attempted
         THEN: It is refused naming which of the two was not found, rather
               than reporting success for a move that never happened
        """
        with pytest.raises(ValueError, match=message):
            move_task(identifier, "Tasks", destination)


class TestSearchTasks:
    """
    Tests for searching tasks.

    Search returns ranked results, so a hit carries its task as a payload
    alongside its score. The guarantees below are the ones substring search
    made and ranking must keep: found by headline, by ticket, by body, across
    both sections, case-insensitively, and empty when there is nothing.
    """

    def test_a_task_is_found_by_headline_ticket_or_body(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        GIVEN: tasks with distinctive headlines, ticket IDs and body text
        WHEN:  each is searched for
        THEN:  the task is found

        A ticket ID stays one term rather than splitting into "jira" and
        "1234", which is what makes searching for it precise.
        """
        by_headline = search_tasks("authentication").payloads
        by_ticket = search_tasks("JIRA-1234").payloads
        by_body = search_tasks("auth flow").payloads

        with check:
            assert any(
                "authentication" in t.headline.lower() for t in by_headline
            )
        with check:
            assert [t for t in by_ticket if "JIRA-1234" in t.headline]
        with check:
            assert any("auth" in t.content.lower() for t in by_body)

    def test_search_spans_both_sections_and_ignores_case(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        GIVEN: matching tasks in the active and the completed section
        WHEN:  a term common to both is searched for, in any case
        THEN:  both are returned, and case makes no difference
        """
        found = search_tasks("JIRA").payloads

        with check:
            assert {t.section for t in found} == {"Tasks", "Completed Tasks"}
        with check:
            assert len(search_tasks("authentication").hits) == len(
                search_tasks("AUTHENTICATION").hits
            )

    def test_a_search_for_something_absent_comes_back_empty(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        GIVEN: a query naming something no task contains
        WHEN:  it is searched for
        THEN:  nothing is returned and the unknown term is reported

        Ranking is generous about what matches, so this is the guarantee most
        at risk from it.
        """
        results = search_tasks("xyzzy-not-found")

        with check:
            assert not results.hits
        with check:
            assert results.absent_terms == ["xyzzy-not-found"]

    def test_search_can_be_narrowed_to_a_section_or_to_headlines(
        self, sample_tasks_file: TasksFileInfo
    ) -> None:
        """
        GIVEN: matching tasks in both sections
        WHEN:  the search is restricted to one section, and separately to
               headlines
        THEN:  each restriction narrows the result accordingly
        """
        active = search_tasks("JIRA", section="Tasks").payloads
        headlines = search_tasks("JIRA", headline_only=True).payloads

        with check:
            assert {t.section for t in active} == {"Tasks"}
        with check:
            assert headlines, "the ticket is in the headlines"


class TestFormatSimpleDiff:
    """
    Tests for the diff a tool shows alongside what it changed.

    This is what a caller reads to see whether an edit did what they meant,
    so it has to name every line that moved and say so plainly when none did.
    """

    @pytest.mark.parametrize(
        "old, new, expected",
        [
            pytest.param(
                "line1\nline2",
                "line1\nline2\nline3",
                ["+ line3"],
                id="addition",
            ),
            pytest.param(
                "line1\nline2\nline3",
                "line1\nline2",
                ["− line3"],
                id="deletion",
            ),
            pytest.param(
                "- [ ] Pending item",
                "- [X] Pending item",
                ["− - [ ] Pending item", "+ - [X] Pending item"],
                id="replacement",
            ),
            pytest.param(
                "line1\nline2", "line1\nline2", ["no changes"], id="unchanged"
            ),
        ],
    )
    def test_the_diff_names_every_line_that_moved(
        self, old: str, new: str, expected: list[str]
    ):
        """
        GIVEN: Two versions of some content
         WHEN: They are diffed for display
         THEN: An added line is marked +, a removed one −, and a changed
               line appears as both -- so a caller sees what the edit did to
               each line rather than being told only that something changed
          AND: Identical content says so, since an empty diff is otherwise
               indistinguishable from a diff that failed to run
        """
        diff = format_simple_diff(old, new).lower()

        for fragment in expected:
            with check:
                assert fragment.lower() in diff


def high_level_checklist() -> str:
    """The High Level Tasks section as it stands in the file."""
    text = global_state.config.tasks_file.read_text()
    body = text.split("* High Level Tasks (in order)", 1)[1]

    return body.split("\n* ", 1)[0]


class TestHighLevelTasksChecklist:
    """
    The checklist that summarises the task list.

    It is a second record of the same work, so what it is really promising is
    that it keeps up: a task added or finished without its line moving leaves
    the summary saying something the task list contradicts.
    """

    def test_a_new_task_joins_the_checklist_under_its_own_description(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A new task whose headline leads with a ticket
         WHEN: It is created
         THEN: An unticked line for it appears in the checklist, described by
               what the work is rather than by its ticket -- the checklist is
               read top to bottom to decide what to do next, and a column of
               ticket numbers does not answer that
        """
        create_task(
            "Tasks",
            make_task("JIRA-456 Refactor payment module", "task-jira-456"),
        )
        checklist = high_level_checklist()

        with check:
            assert "- [ ] Refactor payment module" in checklist
        with check:
            assert "JIRA-456" not in checklist

    def test_finishing_a_task_ticks_its_line(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: An active task with a line in the checklist
         WHEN: It is marked DONE
         THEN: Its line is ticked, so the summary and the task list agree on
               what is finished
        """
        update_task(
            "task-jira-1234",
            make_task(
                "JIRA-1234 Fix authentication bug",
                "task-jira-1234",
                status="DONE",
            ),
        )

        assert "- [X] Fix authentication bug" in high_level_checklist()


class TestUUIDGeneration:
    """Tests for UUID generation when creating tasks."""

    def test_a_task_created_without_one_is_given_a_real_uuid(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A task entry carrying no :ID:
         WHEN: The task is created
         THEN: It is given a UUID4, uppercased the way org writes them, so
               org-mode's own id machinery can address it
        """
        create_task("Tasks", make_task("Task without UUID", "task-no-uuid"))

        (task,) = list_tasks("Tasks")

        with check:
            assert uuid.UUID(task.id).version == 4
        with check:
            assert task.id == task.id.upper()

    def test_a_task_that_brings_its_own_uuid_keeps_it(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A task entry that already names an :ID:
         WHEN: The task is created
         THEN: That id is kept, since it is how anything already referring to
               this task finds it -- minting a fresh one would orphan those
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

        create_task("Tasks", task_with_uuid)

        # Verify the UUID was preserved
        tasks = list_tasks("Tasks")
        assert len(tasks) == 1
        assert tasks[0].id == existing_uuid


class TestTaskIDExtraction:
    """The :ID: on disk is the :ID: a reader hands back."""

    @pytest.mark.parametrize(
        "read",
        [
            pytest.param(lambda: list_tasks("Tasks")[0], id="list_tasks"),
            pytest.param(lambda: find_task("task-with-id")[0], id="find_task"),
        ],
    )
    def test_the_id_in_the_drawer_survives_the_trip_out(
        self, temp_org_dir: Path, read
    ):
        """
        GIVEN: A task whose drawer names an :ID:
         WHEN: It is read back, by listing its section or by looking it up
         THEN: It carries that same id either way

        Both readers build their own Task, so an id read correctly by one and
        dropped by the other is the shape this goes wrong in -- which is why
        it is asserted of each rather than of whichever came to hand.
        """
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org(
                [
                    make_task(
                        headline="Task with explicit ID",
                        custom_id="task-with-id",
                        task_id="C5045326-9DC8-4F1E-A895-8895720DD928",
                    )
                ],
                [],
            )
        )

        assert read().id == "C5045326-9DC8-4F1E-A895-8895720DD928"


class TestTaskTimestamps:
    """
    When each timestamp is written, and in which of org's two forms.

    The bracket is not decoration. An active timestamp ``<...>`` is one org
    puts on the agenda; an inactive ``[...]`` is a record that something
    happened. So :CREATED: and :CLOSED: are active and :MODIFIED: is not --
    every edit landing on the agenda would bury the dates that matter.
    """

    def test_each_timestamp_is_written_at_its_moment_in_org_s_own_form(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A task created, then edited, then finished
         WHEN: The drawer is read after each step
         THEN: :CREATED: is stamped at creation, :MODIFIED: at the edit and
               :CLOSED: when it is finished, each only once its moment has
               come
          AND: :CREATED: and :CLOSED: are active timestamps and :MODIFIED: is
               inactive, so finishing a task shows on the agenda and merely
               editing one does not
        """
        create_task("Tasks", make_task("Task", "task-x"))
        (created,) = list_tasks("Tasks")

        with check:
            assert created.created.startswith("<") and created.created.endswith(
                ">"
            )
        with check:
            assert created.closed == "", (
                "nothing is closed the moment it is made"
            )

        update_task("task-x", make_task("Task, revised", "task-x"))
        edited, _, _, _ = find_task("task-x")

        with check:
            assert edited.modified.startswith("[") and edited.modified.endswith(
                "]"
            )
        with check:
            assert edited.closed == "", "an edit is not a completion"

        update_task(
            "task-x", make_task("Task, revised", "task-x", status="DONE")
        )
        finished, _, _, _ = find_task("task-x")

        with check:
            assert finished.closed.startswith("<") and finished.closed.endswith(
                ">"
            )

    @pytest.mark.parametrize(
        "entry",
        [
            pytest.param(
                make_task("Finished work", "task-reopen", status="DONE"),
                id="closed-was-never-set",
            ),
            pytest.param(None, id="closed-was-set-by-finishing-it"),
        ],
    )
    def test_reopening_a_task_leaves_it_with_no_closed_timestamp(
        self, temp_org_dir: Path, entry: str | None
    ):
        """
        GIVEN: A finished task, either one this server closed or one written
               by hand that never carried a :CLOSED: at all
         WHEN: It is reopened
         THEN: It carries no :CLOSED:, and the property is gone from the
               drawer rather than left blank -- a date saying it was finished
               contradicts the state saying it is not
          AND: Reopening the hand-written one does not fail for want of a
               property to clear

        The two are checked together because the clearing is one line, and
        the way it breaks is by assuming the property is there to remove.
        """
        # `None` means: let the server set :CLOSED: itself, by finishing a
        # task that starts out open. The other case is a DONE task that never
        # had one, which is how a hand-written or long-lived task arrives.
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org(
                [entry or make_task("Finished work", "task-reopen")], []
            )
        )
        if entry is None:
            update_task(
                "task-reopen",
                make_task("Finished work", "task-reopen", status="DONE"),
            )
            assert find_task("task-reopen")[0].closed, "fixture"

        update_task("task-reopen", make_task("Finished work", "task-reopen"))
        task, _, _, _ = find_task("task-reopen")

        with check:
            assert task.status == "TODO"
        with check:
            assert task.closed == ""
        with check:
            assert "CLOSED" not in task.properties
        with check:
            assert task.modified, "reopening is an edit and is recorded as one"

    def test_reopening_with_the_drawer_it_was_given_drops_the_closed_date(
        self, temp_org_dir: Path
    ):
        """
        GIVEN: A finished task, and a caller who read it, changed DONE back to
               TODO, and submitted the whole entry back -- :CLOSED: line and
               all, since that is what they were handed
         WHEN: The update is applied
         THEN: :CLOSED: is gone, because the status the caller sent is the
               instruction and the stale date they copied along with it is not

        The other reopening path never carries a :CLOSED: to begin with, so
        this is the one that needs the property actively removed rather than
        merely not copied forward.
        """
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org([make_task("Finished work", "task-reopen")], [])
        )
        update_task(
            "task-reopen",
            make_task("Finished work", "task-reopen", status="DONE"),
        )
        closed_at = find_task("task-reopen")[0].closed
        assert closed_at, "fixture"

        update_task(
            "task-reopen",
            f"** TODO Finished work\n"
            f":PROPERTIES:\n"
            f"   :CUSTOM_ID: task-reopen\n"
            f"   :CLOSED:   {closed_at}\n"
            f":END:\n",
        )
        task, _, _, _ = find_task("task-reopen")

        with check:
            assert task.status == "TODO"
        with check:
            assert task.closed == ""
        with check:
            assert "CLOSED" not in task.properties

    def test_a_finished_task_edited_again_keeps_the_time_it_was_finished(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: A task already finished
         WHEN: It is edited without reopening it
         THEN: :CLOSED: still holds the time it was finished, and :MODIFIED:
               moves -- when the work was done is a fact about the work, and
               correcting a typo afterwards does not change it
        """
        update_task(
            "task-new-feature",
            make_task(
                "Implement new feature", "task-new-feature", status="DONE"
            ),
        )
        finished_at = find_task("task-new-feature")[0].closed
        assert finished_at, "fixture"

        update_task(
            "task-new-feature",
            make_task(
                "Implement new feature, revised",
                "task-new-feature",
                status="DONE",
            ),
        )
        task, _, _, _ = find_task("task-new-feature")

        with check:
            assert task.closed == finished_at
        with check:
            assert task.modified


class TestPropertyPreservation:
    """
    Tests that heading_to_org_string renders :PROPERTIES: and that update_task
    preserves them even when the submitted entry omits the drawer.

    Regression tests for the bug where :ID:, :CUSTOM_ID:, and :PROJECT:
    were silently dropped on update because heading_to_org_string did not
    emit the :PROPERTIES: drawer, so round-tripped entries never included it.
    """

    def test_rendering_a_task_back_out_keeps_its_drawer(self):
        """
        GIVEN: A task entry carrying a :PROPERTIES: drawer
         WHEN: It is parsed and rendered back to org text
         THEN: The drawer and every property in it survive

        This is the render an update is built from, so a property missing
        here is a property deleted from the file on the next write.
        """
        entry = (
            "** TODO Task with properties\n"
            ":PROPERTIES:\n"
            "   :ID:       AAAA-BBBB-CCCC-DDDD-EEEEFFFF0000\n"
            "   :CUSTOM_ID: task-test\n"
            "   :PROJECT:  project-myapp\n"
            ":END:\n"
            "\n"
            "*** Description\n"
            "Test description.\n"
        )
        heading = parse_task_entry(entry)
        result = heading_to_org_string(heading)

        assert ":PROPERTIES:" in result
        assert ":END:" in result
        assert "AAAA-BBBB-CCCC-DDDD-EEEEFFFF0000" in result
        assert "task-test" in result
        assert "project-myapp" in result

    @pytest.mark.parametrize(
        "prop,value",
        [
            ("ID", "DEAD-BEEF-1234-5678-ABCD-EF0123456789"),
            ("CUSTOM_ID", "task-preserve-props"),
            ("PROJECT", "project-myapp"),
        ],
    )
    def test_update_preserves_property_when_entry_omits_it(
        self, temp_org_dir: Path, prop: str, value: str
    ) -> None:
        """
        GIVEN: A task carrying :ID:, :CUSTOM_ID: and :PROJECT:, and a
               replacement entry written without a drawer at all
         WHEN: The task is updated
         THEN: Each property is still there, because an update replaces the
               content a caller wrote and not the bookkeeping the server
               keeps -- a dropped :CUSTOM_ID: makes every link to the task
               dangle, and a dropped :PROJECT: unfiles it
        """
        task_entry = (
            "** TODO Task to test property preservation\n"
            ":PROPERTIES:\n"
            "   :ID:       DEAD-BEEF-1234-5678-ABCD-EF0123456789\n"
            "   :CUSTOM_ID: task-preserve-props\n"
            "   :PROJECT:  project-myapp\n"
            ":END:\n"
            "\n"
            "*** Description\n"
            "Original description.\n"
        )
        tasks_file = temp_org_dir / "tasks.org"
        tasks_file.write_text(make_tasks_org([task_entry], []))

        # Update with an entry that omits the :PROPERTIES: drawer entirely
        minimal_update = (
            "** TODO Task to test property preservation\n"
            "*** Description\n"
            "Updated description, no properties drawer.\n"
        )
        update_task("task-preserve-props", minimal_update)

        _, heading, _, _ = find_task("task-preserve-props")
        assert heading.properties.get(prop) == value
