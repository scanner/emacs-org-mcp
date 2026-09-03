#!/usr/bin/env python
#
"""
Tests for filtering, projecting and summarising the task list.

These exist because an agent kept hand-writing a parser to answer questions
the read tools could not express — and got three confidently wrong answers
doing it. The filter's job is to be the correct parser the server already has,
reachable from a tool call.

So the tests are written against tasks the *parser* returns, never against a
regex over the file. A filter that agreed with a hand-rolled pattern rather
than with the parser would reproduce the bug it exists to remove.
"""

from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.results import MAX_ITEM_LINES, checklist_lines, render
from mcp_server.tasks import (
    format_org_stats,
    list_tasks,
    org_stats,
    search_tasks,
    task_to_record,
)
from tests.conftest import make_task, make_tasks_org


def with_props(entry: str, **props: str) -> str:
    """
    Add drawer properties to a task built by make_task.

    make_task closes the drawer with a bare ``:END:`` and no trailing newline
    when the task has no body, so the insert has to anchor on ``:END:`` itself
    rather than on ``:END:\n``.
    """
    extra = "".join(f"   :{name}: {value}\n" for name, value in props.items())
    return entry.replace(":END:", f"{extra}:END:", 1)


########################################################################
#
@pytest.fixture
def mixed_tasks(temp_org_dir: Path) -> Path:
    """
    Tasks spread over two projects, two sections, and a stray property.

    Deliberately mixed: a filter that quietly matched everything, or nothing,
    would pass against a uniform fixture.
    """
    active = [
        with_props(
            make_task("Widget one", "task-w1", task_items=[(True, "a"), (False, "b")]),
            PROJECT="project-widgets",
            JIRA="GH-1",
        ),
        with_props(
            make_task("Widget two", "task-w2"), PROJECT="widgets"
        ),
        with_props(
            make_task("Gadget one", "task-g1"), PROJECT="project-gadgets"
        ),
        make_task("Unfiled", "task-u1"),
    ]
    completed = [
        with_props(
            make_task("Widget done", "task-w3", status="DONE"),
            PROJECT="project-widgets",
        )
    ]
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(make_tasks_org(active, completed))
    return tasks_file


def ids(tasks) -> list[str]:
    """The CUSTOM_IDs of some tasks, in order."""
    return [t.custom_id for t in tasks]


########################################################################
########################################################################
#
class TestFiltering:
    """Tests for the where filter."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "where, expected",
        [
            pytest.param(None, ["task-w1", "task-w2", "task-g1", "task-u1"], id="no-filter"),
            pytest.param({"PROJECT": "project-widgets"}, ["task-w1", "task-w2"], id="canonical"),
            pytest.param({"PROJECT": "widgets"}, ["task-w1", "task-w2"], id="bare-slug"),
            pytest.param({"PROJECT": "WIDGETS"}, ["task-w1", "task-w2"], id="case-insensitive"),
            pytest.param({"JIRA": "GH-1"}, ["task-w1"], id="undeclared-property"),
            pytest.param({"jira": "gh-1"}, ["task-w1"], id="field-name-any-case"),
            pytest.param({"PROJECT": "widgets", "JIRA": "GH-1"}, ["task-w1"], id="clauses-are-anded"),
            pytest.param({"JIRA": "GH-999"}, [], id="value-nothing-has"),
            pytest.param({"NOSUCHPROP": "x"}, [], id="field-nothing-has"),
        ],
    )
    def test_a_filter_selects_by_any_drawer_property(
        self, mixed_tasks: Path, where, expected
    ):
        """
        GIVEN: tasks carrying different projects, and one with a :JIRA:
        WHEN:  the section is listed with a filter
        THEN:  exactly the matching tasks come back, in file order

        Both spellings of a project select the same tasks, because the format
        defines a project's id as project-<slug> and a caller naming either
        means the same thing. That equivalence is the single query that was
        got wrong repeatedly by hand.

        A property the server has never heard of filters like any other: the
        live file carries :JIRA: on 30 tasks, named nowhere in the code.
        """
        assert ids(list_tasks("Tasks", where)) == expected

    ####################################################################
    #
    def test_a_task_missing_the_field_does_not_match(self, mixed_tasks: Path):
        """
        GIVEN: tasks where only some carry a given property
        WHEN:  that property is filtered on
        THEN:  only the tasks carrying it are returned

        The alternative — treating absence as a match — would make a filter
        for :JIRA: return the whole file, which is the opposite of asking.
        """
        with check:
            assert ids(list_tasks("Tasks", {"JIRA": "GH-1"})) == ["task-w1"]
        with check:
            assert "task-u1" not in ids(list_tasks("Tasks", {"PROJECT": "widgets"}))

    ####################################################################
    #
    def test_status_and_section_filter_though_not_in_the_drawer(
        self, mixed_tasks: Path
    ):
        """
        GIVEN: tasks in both sections
        WHEN:  the pseudo-fields status and section are filtered on
        THEN:  they behave like any other field

        Neither lives in the drawer, and both are what a caller actually wants
        to filter by, so they are worth the special case.
        """
        with check:
            assert ids(list_tasks("Completed Tasks", {"status": "DONE"})) == ["task-w3"]
        with check:
            assert ids(list_tasks("Tasks", {"status": "DONE"})) == []

    ####################################################################
    #
    def test_the_filter_agrees_with_the_parser(self, mixed_tasks: Path):
        """
        GIVEN: every task the parser can see
        WHEN:  each is filtered for the project the parser says it has
        THEN:  the filter returns it

        This is the point of the whole feature. The filter must agree with the
        parser rather than with a pattern over the text, because hand-matching
        the format is exactly what produced wrong answers before.
        """
        for section in ("Tasks", "Completed Tasks"):
            for task in list_tasks(section):
                if not task.project:
                    continue
                with check:
                    assert task.custom_id in ids(
                        list_tasks(section, {"PROJECT": task.project})
                    ), f"{task.custom_id} not returned by its own project"

    ####################################################################
    #
    def test_search_filters_before_it_ranks(self, mixed_tasks: Path):
        """
        GIVEN: tasks in two projects sharing a word
        WHEN:  that word is searched for within one project
        THEN:  only that project's tasks are returned

        Filtering before ranking matters: relevance is then computed over the
        tasks the caller asked about, so scores are not skewed by documents
        that were never candidates.
        """
        results = search_tasks("one", where={"PROJECT": "widgets"})

        assert ids(h.doc.payload for h in results.hits) == ["task-w1"]


########################################################################
########################################################################
#
class TestProjectionAndItems:
    """Tests for showing a property, and for the items detail level."""

    ####################################################################
    #
    def test_a_named_property_is_appended_to_the_line(self, mixed_tasks: Path):
        """
        GIVEN: tasks where only some carry a property
        WHEN:  it is projected onto the result lines
        THEN:  it appears for the tasks that have it and is absent for the
               rest, rather than being shown empty

        An empty column on every second line costs tokens and reads as data.
        """
        tasks = list_tasks("Tasks")
        output = render(
            [task_to_record(t, show=["JIRA"]) for t in tasks],
            tool="list_tasks",
            header="Tasks",
        )

        with check:
            assert "JIRA=GH-1" in output
        with check:
            assert "JIRA=" not in output.replace("JIRA=GH-1", "")

    ####################################################################
    #
    def test_items_shows_the_checklist_and_nothing_else(
        self, mixed_tasks: Path
    ):
        """
        GIVEN: a task with a progress cookie and checkbox items, and body text
        WHEN:  it is rendered at the items level
        THEN:  the cookie and the checkboxes appear, and the prose does not

        This is the "which of these is actually finished" question, which
        otherwise costs a whole task read per record to see one number.
        """
        output = render(
            [task_to_record(t) for t in list_tasks("Tasks", {"CUSTOM_ID": "task-w1"})],
            tool="list_tasks",
            header="Tasks",
            detail="items",
        )

        with check:
            assert "Task items [1/2]" in output
        with check:
            assert "- [X] a" in output and "- [ ] b" in output
        with check:
            assert "Description" not in output, "prose leaked into items"

    ####################################################################
    #
    def test_one_record_cannot_flood_the_page_with_checkboxes(self):
        """
        GIVEN: a task with far more checklist lines than a page should carry
        WHEN:  its checklist is taken
        THEN:  it is capped

        Without the cap a long task costs as much as reading it in full, which
        is the level this exists to avoid.
        """
        body = "\n".join(f"- [ ] item {n}" for n in range(200))

        assert len(checklist_lines(body)) == MAX_ITEM_LINES


########################################################################
########################################################################
#
class TestAggregates:
    """Tests for the counts tool."""

    ####################################################################
    #
    def test_counts_are_reported_without_the_records(self, mixed_tasks: Path):
        """
        GIVEN: tasks across sections and projects, some with checklists
        WHEN:  the counts are gathered and rendered
        THEN:  the totals are right, unfiled tasks are counted as such, and
               the report is a handful of lines rather than a listing

        The whole reason this exists is that shell wins at aggregates: one
        number beats fifty lines reporting a number.
        """
        stats = org_stats()

        with check:
            assert stats.tasks == 5
        with check:
            assert stats.by_section == {"Tasks": 4, "Completed Tasks": 1}
        with check:
            assert stats.by_project["(none)"] == 1
        with check:
            assert stats.by_project["project-widgets"] == 2, (
                "the bare-slug task counts under its own written value"
            )
        with check:
            assert (stats.items_done, stats.items_total) == (1, 2)

        output = format_org_stats(stats)
        with check:
            assert len(output.split("\n")) < 20, "a summary, not a listing"
        with check:
            assert "Widget one" not in output, "no record content"
