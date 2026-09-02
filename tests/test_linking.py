#!/usr/bin/env python
#
"""
Tests for linking a task and a project.

A link is mechanical, so these pin the properties that make it safe to call
without review: both ends are maintained together, calling twice does not
duplicate anything, and unlinking undoes exactly what linking did.

The format matters as much as the behaviour. ``:PROJECT:`` is the project's
``:CUSTOM_ID:`` -- that is what the guides specify, and a shared format is the
point of the server, so a value in any other shape is rewritten rather than
tolerated.
"""

from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.linking import (
    link_task_to_project,
    unlink_task_from_project,
)
from mcp_server.tasks import find_task, update_task
from tests.conftest import make_project, make_task, make_tasks_org


########################################################################
#
@pytest.fixture
def task_and_project(temp_org_dir: Path) -> Path:
    """One task and one project, not yet linked."""
    (temp_org_dir / "tasks.org").write_text(
        make_tasks_org([make_task("GH-48 Build the widget", "task-gh-48")], [])
    )
    (temp_org_dir / "projects" / "widgets.org").write_text(
        make_project(title="Widgets", slug="widgets")
    )
    return temp_org_dir


def project_text(org_dir: Path) -> str:
    """The project file's current contents."""
    return (org_dir / "projects" / "widgets.org").read_text()


def task_project_property(identifier: str) -> str:
    """A task's current :PROJECT: value, or ''."""
    return find_task(identifier)[0].project.strip()


########################################################################
########################################################################
#
class TestLinking:
    """Tests for making and removing a link."""

    ####################################################################
    #
    def test_linking_maintains_both_ends(self, task_and_project: Path):
        """
        GIVEN: a task and a project that are not linked
        WHEN:  they are linked
        THEN:  the task carries the project's CUSTOM_ID and the project lists
               the task, and the result says so for each end

        One call, both ends. Leaving either to the caller is how the two drift
        apart.
        """
        result = link_task_to_project("task-gh-48", "widgets")

        with check:
            assert task_project_property("task-gh-48") == "project-widgets"
        with check:
            assert "#task-gh-48" in project_text(task_and_project)
        with check:
            assert result.task_end == "set"
        with check:
            assert result.project_end == "added"

    ####################################################################
    #
    def test_linking_twice_changes_nothing_the_second_time(
        self, task_and_project: Path
    ):
        """
        GIVEN: a task and project already linked
        WHEN:  they are linked again
        THEN:  nothing is written and both ends report as already correct

        A mechanical operation has to be safe to retry, which is also what
        makes a half-finished link self-healing: re-running completes the
        missing end rather than duplicating the finished one.
        """
        link_task_to_project("task-gh-48", "widgets")
        result = link_task_to_project("task-gh-48", "widgets")

        with check:
            assert not result.changed
        with check:
            assert project_text(task_and_project).count("#task-gh-48") == 1

    ####################################################################
    #
    def test_renaming_a_task_does_not_produce_a_second_link(
        self, task_and_project: Path
    ):
        """
        GIVEN: a linked task whose headline has since been rewritten
        WHEN:  it is linked again
        THEN:  it still has exactly one link

        The rendered link carries the headline, so a comparison on line text
        would see the old line as different and append a second. Matching the
        #task-id anchor is what makes a rename survivable -- and a rename is
        the ordinary case, not an edge one.
        """
        link_task_to_project("task-gh-48", "widgets")

        update_task(
            "task-gh-48",
            make_task("GH-48 Build the widget, revised scope", "task-gh-48"),
        )
        link_task_to_project("task-gh-48", "widgets")

        assert project_text(task_and_project).count("#task-gh-48") == 1

    ####################################################################
    #
    def test_unlinking_removes_both_ends(self, task_and_project: Path):
        """
        GIVEN: a linked task and project
        WHEN:  they are unlinked
        THEN:  the property is cleared and the link line is gone

        A link that cannot be undone without hand-editing is half a feature.
        """
        link_task_to_project("task-gh-48", "widgets")
        result = unlink_task_from_project("task-gh-48", "widgets")

        with check:
            assert task_project_property("task-gh-48") == ""
        with check:
            assert "#task-gh-48" not in project_text(task_and_project)
        with check:
            assert result.task_end == "cleared"
        with check:
            assert result.project_end == "removed"

    ####################################################################
    #
    def test_unlinking_something_unlinked_changes_nothing(
        self, task_and_project: Path
    ):
        """
        GIVEN: a task and project that were never linked
        WHEN:  they are unlinked
        THEN:  nothing is written and both ends report as already correct
        """
        result = unlink_task_from_project("task-gh-48", "widgets")

        assert not result.changed


########################################################################
########################################################################
#
class TestFormatIsEnforced:
    """
    Tests that linking normalises the shared format.

    A common format across tasks, projects and journals is the point of the
    server: another tool reading these files has to find the same field in the
    same shape. The live tasks.org holds two different spellings of
    ``:PROJECT:`` precisely because nothing ever wrote it in one place.
    """

    ####################################################################
    #
    def test_a_non_canonical_project_value_is_rewritten(
        self, task_and_project: Path
    ):
        """
        GIVEN: a task whose :PROJECT: names the right project in the wrong
               form -- the slug rather than the CUSTOM_ID
        WHEN:  it is linked to that project
        THEN:  the value is rewritten to the canonical CUSTOM_ID, and the
               result says it was normalised rather than merely set

        This repairs an unsanctioned value through ordinary use, so no
        migration is needed for the ones already in the wild.
        """
        update_task(
            "task-gh-48",
            "** TODO GH-48 Build the widget\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-48\n"
            "   :PROJECT:  widgets\n"
            ":END:\n",
        )
        assert task_project_property("task-gh-48") == "widgets", "fixture"

        result = link_task_to_project("task-gh-48", "widgets")

        with check:
            assert task_project_property("task-gh-48") == "project-widgets"
        with check:
            assert result.task_end == "normalized"

    ####################################################################
    #
    def test_relinking_to_a_different_project_is_refused(
        self, task_and_project: Path
    ):
        """
        GIVEN: a task already linked to one project
        WHEN:  it is linked to a different one
        THEN:  it is refused, naming the project it is already linked to

        Silently repointing the property would leave the first project's
        Related Tasks pointing at a task that no longer claims it -- the exact
        half-state this tool exists to prevent.
        """
        (task_and_project / "projects" / "gadgets.org").write_text(
            make_project(title="Gadgets", slug="gadgets")
        )
        link_task_to_project("task-gh-48", "widgets")

        with pytest.raises(ValueError, match="already linked"):
            link_task_to_project("task-gh-48", "gadgets")

    ####################################################################
    #
    def test_a_task_without_a_custom_id_cannot_be_linked(
        self, task_and_project: Path
    ):
        """
        GIVEN: a task with no :CUSTOM_ID:
        WHEN:  it is linked to a project
        THEN:  it is refused, explaining that there is nothing to link to

        The link is an anchor to the CUSTOM_ID, so without one there is no
        link to write -- better to say so than to write a broken anchor.
        """
        (task_and_project / "tasks.org").write_text(
            make_tasks_org(["** TODO Anonymous task"], [])
        )

        with pytest.raises(ValueError, match="no :CUSTOM_ID:"):
            link_task_to_project("Anonymous", "widgets")
