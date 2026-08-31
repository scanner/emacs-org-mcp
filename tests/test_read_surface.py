#!/usr/bin/env python
#
"""
Tests that the read tools return what their descriptions promise.

A tool description is part of the API contract an agent reads before deciding
whether a call is affordable. On 2026-08-31 ``list_tasks`` advertised "Returns
task names, headlines, status, and full content" while returning one line per
task, and an agent used shell commands for orientation rather than pay for a
call that would have cost about 2,650 tokens. The description was the defect.

These tests pin the claim rather than the wording. Every list and search tool
returns a bounded number of lines per record and does not include record
bodies, so a formatter that regressed to dumping content would fail here even
though its description still read correctly.
"""

from pathlib import Path

import pytest

from mcp_server.journal import format_journal_list, parse_journal_entries
from mcp_server.projects import format_project_list, list_projects
from mcp_server.tasks import format_task_list, list_tasks, search_tasks
from mcp_server.tools import format_search_results
from tests.conftest import make_journal_file, make_task, make_tasks_org

# Bodies are built from this so a formatter that emits them is unmistakable in
# the failure, rather than showing up only as a line count that drifted.
BODY_MARKER = "BODY_TEXT_THAT_MUST_NOT_APPEAR_IN_A_LISTING"

RECORD_COUNT = 12
BODY_LINES = 40

# Lines each record is allowed to occupy, by tool. A record's own body runs to
# BODY_LINES, so any budget below that fails the moment content is included.
LINE_BUDGET = {
    "list_tasks": 1,
    "search_tasks": 1,
    # One line for the entry, plus the two-line body preview the description
    # promises.
    "list_journal_entries": 3,
    "search_journal": 1,
    # One line for the project, plus its one-line description preview.
    "list_projects": 2,
    "search_projects": 1,
}

# Headers, separators, blank lines and any parser warning.
HEADER_ALLOWANCE = 12


def big_body(n: int) -> str:
    """A body long enough that including it blows every budget here."""
    return "\n".join(
        f"{BODY_MARKER} line {i} of record {n}" for i in range(BODY_LINES)
    )


def assert_bounded(output: str, tool: str, records: int) -> None:
    """Assert a listing neither embeds bodies nor grows without bound."""
    assert BODY_MARKER not in output, (
        f"{tool} included record bodies in a listing. Its description says it "
        f"does not, and callers size their requests on that promise."
    )

    budget = HEADER_ALLOWANCE + LINE_BUDGET[tool] * records
    actual = len(output.split("\n"))
    assert actual <= budget, (
        f"{tool} returned {actual} lines for {records} records, over its "
        f"budget of {budget} ({LINE_BUDGET[tool]} per record plus "
        f"{HEADER_ALLOWANCE} for headers)."
    )


########################################################################
#
@pytest.fixture
def loaded_tasks_file(temp_org_dir: Path) -> Path:
    """A tasks.org whose every task carries a long body."""
    tasks = [
        make_task(
            headline=f"TICKET-{n} Task number {n}",
            custom_id=f"task-{n}",
            description=big_body(n),
        )
        for n in range(RECORD_COUNT)
    ]
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(make_tasks_org(tasks, []))
    return tasks_file


########################################################################
#
@pytest.fixture
def loaded_journal_file(temp_org_dir: Path) -> Path:
    """A journal file whose every entry carries a long body."""
    from datetime import date

    entries = [
        f"** {n:02d}:00 Entry number {n} :work:\n{big_body(n)}"
        for n in range(RECORD_COUNT)
    ]
    journal_dir = temp_org_dir / "journal"
    file_date = date(2026, 8, 31)
    path = journal_dir / file_date.strftime("%Y%m%d")
    path.write_text(make_journal_file(entries, file_date))
    return path


########################################################################
########################################################################
#
class TestListingsAreBounded:
    """
    Tests that a listing stays compact however large its records are.

    Every record in these fixtures carries a 40-line body, so a formatter that
    includes bodies exceeds its budget many times over.
    """

    ####################################################################
    #
    def test_list_tasks_returns_a_line_per_task(self, loaded_tasks_file: Path):
        """
        GIVEN: a tasks.org whose tasks have long bodies
        WHEN:  a section is listed
        THEN:  each task costs one line and no body text is returned

        Callers decide whether to call this based on its description saying so.
        """
        output = format_task_list(list_tasks("Tasks"), "Tasks")

        assert_bounded(output, "list_tasks", RECORD_COUNT)

    ####################################################################
    #
    def test_search_tasks_returns_a_line_per_match(
        self, loaded_tasks_file: Path
    ):
        """
        GIVEN: a tasks.org whose tasks have long bodies
        WHEN:  a query matches text that appears only inside those bodies
        THEN:  each match costs one line and no body text is returned

        Matching on body text is what makes this the easy case to get wrong:
        the matching content is exactly what a formatter is tempted to echo.
        """
        matches = search_tasks(BODY_MARKER)
        assert len(matches) == RECORD_COUNT, "fixture should match every task"

        output = format_search_results(matches, "task")

        assert_bounded(output, "search_tasks", RECORD_COUNT)

    ####################################################################
    #
    def test_list_journal_entries_returns_a_preview_not_a_body(
        self, loaded_journal_file: Path
    ):
        """
        GIVEN: a journal file whose entries have long bodies
        WHEN:  the day is listed
        THEN:  each entry costs its line plus a short preview, never its body

        This tool does return the first two body lines, which its description
        calls a preview. The budget is what keeps a preview from becoming the
        whole entry.
        """
        entries = parse_journal_entries(loaded_journal_file)
        output = format_journal_list(entries, "2026-08-31")

        budget = HEADER_ALLOWANCE + LINE_BUDGET["list_journal_entries"] * len(
            entries
        )
        assert len(output.split("\n")) <= budget

    ####################################################################
    #
    def test_list_projects_returns_a_line_and_a_preview(
        self, sample_project_files
    ):
        """
        GIVEN: a projects directory
        WHEN:  projects are listed
        THEN:  each project costs its line plus a one-line description preview
        """
        projects = list_projects(None)
        output = format_project_list(projects)

        assert_bounded(output, "list_projects", len(projects))
