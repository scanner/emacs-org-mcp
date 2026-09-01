#!/usr/bin/env python
#
"""
Tests that a task's position in its section means what the workflow says.

The top of the Tasks section is what to work on next. A task that is never
picked up drifts down, until its position is itself the signal that it no
longer matters. That makes position load-bearing data, not presentation.

Every entry point used to file work at the *bottom* -- exactly where "no longer
relevant" lives:

- ``create_task`` appended, so brand new work arrived stale
- ``move_task`` appended
- ``update_task`` appended whenever the section changed, in either direction,
  so reopening a DONE task buried it

Only a same-section update preserved position. The cost was invisible because
nothing failed: the file was correct, just ordered against its own meaning, and
it was corrected by hand afterwards.
"""

import re
from pathlib import Path

import pytest
from pytest_check import check

from mcp_server import tasks as tasks_module
from mcp_server.tasks import (
    create_task,
    move_task,
    reorder_task,
    resort_completed_tasks,
    update_task,
)
from tests.conftest import make_task, make_tasks_org

SECTION_RE = re.compile(r"^\* (.+?)(?:[ \t]+\[\d*/\d*\])?[ \t]*$")
CUSTOM_ID_RE = re.compile(r"^\s*:CUSTOM_ID:\s*(\S+)\s*$")


def section_order(tasks_file: Path, section: str) -> list[str]:
    """
    Return the CUSTOM_IDs of a section's tasks, in the order they sit in the
    file.

    Args:
        tasks_file: The tasks.org to read
        section: Section name to read the order of

    Returns:
        CUSTOM_IDs top to bottom.

    Note:
        Reads the raw text rather than asking the parser, because file order
        *is* the thing under test and a parser that reordered would otherwise
        agree with itself.
    """
    order: list[str] = []
    current: str | None = None

    for line in tasks_file.read_text().split("\n"):
        if match := SECTION_RE.match(line):
            current = match.group(1).strip()
        elif current == section and (match := CUSTOM_ID_RE.match(line)):
            order.append(match.group(1))

    return order


########################################################################
#
@pytest.fixture
def three_of_each(temp_org_dir: Path) -> Path:
    """A tasks.org with three active and three completed tasks."""
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(
        make_tasks_org(
            [make_task(f"Active {n}", f"task-active-{n}") for n in (1, 2, 3)],
            [
                make_task(f"Done {n}", f"task-done-{n}", status="DONE")
                for n in (1, 2, 3)
            ],
        )
    )
    return tasks_file


########################################################################
########################################################################
#
class TestNewWorkArrivesAtTheTop:
    """Tests that every entry point files a task where it will be seen."""

    ####################################################################
    #
    def test_a_created_task_goes_to_the_top(self, three_of_each: Path):
        """
        GIVEN: a section that already holds several tasks
        WHEN:  a new task is created in it
        THEN:  it is first in the section

        A task is created because someone intends to do it, so filing it
        below work that has already been passed over inverts the meaning of
        the list.
        """
        create_task("Tasks", make_task("Brand new", "task-new"))

        assert section_order(three_of_each, "Tasks")[0] == "task-new"

    ####################################################################
    #
    def test_a_moved_task_goes_to_the_top_of_its_new_section(
        self, three_of_each: Path
    ):
        """
        GIVEN: tasks in both sections
        WHEN:  a task is moved from one section to the other
        THEN:  it is first in the section it arrives in
        """
        move_task("task-active-2", "Tasks", "Completed Tasks")

        assert (
            section_order(three_of_each, "Completed Tasks")[0]
            == "task-active-2"
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "identifier, new_status, section",
        [
            pytest.param(
                "task-active-3", "DONE", "Completed Tasks", id="finishing-work"
            ),
            pytest.param("task-done-3", "TODO", "Tasks", id="reopening-work"),
        ],
    )
    def test_a_status_change_puts_the_task_at_the_top(
        self, three_of_each: Path, identifier, new_status, section
    ):
        """
        GIVEN: a task whose status is about to change section
        WHEN:  it is updated
        THEN:  it is first in the section it lands in

        Both directions matter and for different reasons. Finishing work
        newest-first makes the completed list a record of what was just done.
        Reopening a task is a strong signal that it matters now, so burying it
        is precisely backwards.
        """
        update_task(
            identifier,
            make_task(f"Rewritten {identifier}", identifier, status=new_status),
        )

        assert section_order(three_of_each, section)[0] == identifier

    ####################################################################
    #
    def test_an_update_that_stays_put_does_not_move_the_task(
        self, three_of_each: Path
    ):
        """
        GIVEN: a task in the middle of its section
        WHEN:  it is edited without changing status
        THEN:  the section's order is unchanged

        Control. Editing a task says nothing about its priority, so an edit
        must not quietly promote it -- which is what a naive "everything goes
        to the top" rule would do.
        """
        before = section_order(three_of_each, "Tasks")

        update_task("task-active-2", make_task("Edited", "task-active-2"))

        with check:
            assert section_order(three_of_each, "Tasks") == before
        with check:
            assert before[1] == "task-active-2", "fixture should be in middle"


########################################################################
########################################################################
#
class TestReorderTask:
    """Tests for moving a task within its section."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "position, relative_to, expected",
        [
            pytest.param(
                "top",
                None,
                ["task-active-3", "task-active-1", "task-active-2"],
                id="to-the-top",
            ),
            pytest.param(
                "bottom",
                None,
                ["task-active-1", "task-active-2", "task-active-3"],
                id="to-the-bottom-is-a-no-op-here",
            ),
            pytest.param(
                "before",
                "task-active-2",
                ["task-active-1", "task-active-3", "task-active-2"],
                id="before-related-work",
            ),
            pytest.param(
                "after",
                "task-active-1",
                ["task-active-1", "task-active-3", "task-active-2"],
                id="after-related-work",
            ),
        ],
    )
    def test_a_task_can_be_placed_relative_to_the_rest(
        self, three_of_each: Path, position, relative_to, expected
    ):
        """
        GIVEN: a section holding several tasks
        WHEN:  one of them is repositioned
        THEN:  the section holds the same tasks in the requested order

        before and after exist because work is usually prioritised relative to
        related work -- before for pre-work, after for follow-on. Neither
        implies a dependency: a task placed after another may proceed while
        that one is still open.
        """
        reorder_task("task-active-3", position, relative_to)

        assert section_order(three_of_each, "Tasks") == expected

    ####################################################################
    #
    def test_reordering_works_in_the_completed_section_too(
        self, three_of_each: Path
    ):
        """
        GIVEN: a completed section
        WHEN:  one of its tasks is repositioned
        THEN:  it moves

        Completed tasks are newest-first by default, but may be reordered by
        other logic on request, so this is not restricted to active work.
        """
        reorder_task("task-done-3", "top")

        assert section_order(three_of_each, "Completed Tasks")[0] == (
            "task-done-3"
        )

    ####################################################################
    #
    def test_a_reorder_reports_where_the_task_landed(self, three_of_each: Path):
        """
        GIVEN: a task being repositioned
        WHEN:  the reorder completes
        THEN:  it reports the section and the task's new position

        Position is priority, so a caller that just set one should be told
        what it now is rather than having to re-read the section.
        """
        headline, section, index = reorder_task(
            "task-active-1", "after", "task-active-2"
        )

        with check:
            assert section == "Tasks"
        with check:
            assert index == 2
        with check:
            assert "Active 1" in headline

    ####################################################################
    #
    @pytest.mark.parametrize(
        "position, relative_to, message",
        [
            pytest.param("before", None, "needs relative_to", id="no-anchor"),
            pytest.param(
                "after", "task-done-1", "no such task", id="anchor-elsewhere"
            ),
            pytest.param("sideways", None, "Unknown position", id="nonsense"),
        ],
    )
    def test_an_impossible_placement_is_refused(
        self, three_of_each: Path, position, relative_to, message
    ):
        """
        GIVEN: a placement that cannot be honoured
        WHEN:  a reorder is attempted
        THEN:  it is refused with a message naming the problem

        An anchor in a different section is the interesting one: the task
        exists, so a silent no-op would look like success while leaving the
        order untouched.
        """
        with pytest.raises(ValueError, match=message):
            reorder_task("task-active-1", position, relative_to)

    ####################################################################
    #
    def test_a_reorder_that_would_lose_a_task_is_refused(
        self, three_of_each: Path, mocker
    ):
        """
        GIVEN: a reorder whose placement drops a task from the section
        WHEN:  it is attempted
        THEN:  it is refused, naming the task that went missing, and the file
               is left unchanged

        A reorder is a pure permutation, so the section must hold exactly the
        same tasks afterwards. That is a stricter check than the general write
        guard and it exists to catch the children-list surgery going wrong.
        """
        original = three_of_each.read_text()

        # Simulate the list surgery dropping a task on the floor.
        real_place = tasks_module.place_child

        def lossy(section, child, position="top", relative_to=None):
            real_place(section, child, position, relative_to)
            section.children = list(section.children)[1:]

        mocker.patch.object(tasks_module, "place_child", side_effect=lossy)

        with pytest.raises(ValueError, match="same tasks"):
            reorder_task("task-active-3", "top")

        assert three_of_each.read_text() == original


########################################################################
########################################################################
#
class TestResortCompletedTasks:
    """Tests for the one-off sort of the completed section."""

    ####################################################################
    #
    def test_completed_tasks_sort_newest_first(self, temp_org_dir: Path):
        """
        GIVEN: completed tasks carrying :CLOSED: dates in no useful order,
               some of them with no date at all
        WHEN:  the completed section is re-sorted
        THEN:  dated tasks come first, newest first, and undated ones follow
               in the order they were already in

        Undated tasks sort last rather than being given an invented date:
        there is nothing to place them by, and guessing would be worse than
        leaving them where they are.
        """
        tasks_file = temp_org_dir / "tasks.org"
        completed = [
            make_task("Oldest", "task-oldest", status="DONE"),
            make_task("Undated A", "task-undated-a", status="DONE"),
            make_task("Newest", "task-newest", status="DONE"),
            make_task("Undated B", "task-undated-b", status="DONE"),
            make_task("Middle", "task-middle", status="DONE"),
        ]
        dates = {
            "task-oldest": "<2026-01-01 Thu 09:00>",
            "task-newest": "<2026-08-30 Sun 09:00>",
            "task-middle": "<2026-05-15 Fri 09:00>",
        }
        text = make_tasks_org([make_task("Active", "task-active")], completed)
        for custom_id, closed in dates.items():
            text = text.replace(
                f"   :CUSTOM_ID: {custom_id}\n",
                f"   :CUSTOM_ID: {custom_id}\n   :CLOSED:   {closed}\n",
            )
        tasks_file.write_text(text)

        total, moved = resort_completed_tasks()

        with check:
            assert section_order(tasks_file, "Completed Tasks") == [
                "task-newest",
                "task-middle",
                "task-oldest",
                "task-undated-a",
                "task-undated-b",
            ]
        with check:
            assert total == 5
        with check:
            assert moved > 0, "should report that it changed something"
        with check:
            assert section_order(tasks_file, "Tasks") == ["task-active"], (
                "the active section must not be touched"
            )

    ####################################################################
    #
    def test_re_sorting_an_already_sorted_section_changes_nothing(
        self, three_of_each: Path
    ):
        """
        GIVEN: a completed section already in the order the sort would produce
        WHEN:  it is re-sorted
        THEN:  the order is unchanged and nothing is reported as moved

        Idempotent, so running it twice is safe and a caller can run it
        without first working out whether it is needed.
        """
        before = section_order(three_of_each, "Completed Tasks")

        resort_completed_tasks()
        _, moved = resort_completed_tasks()

        with check:
            assert section_order(three_of_each, "Completed Tasks") == before
        with check:
            assert moved == 0
