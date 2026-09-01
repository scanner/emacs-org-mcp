#!/usr/bin/env python
#
"""
Tests that the read tools return what their descriptions promise.

A tool description is part of the API contract an agent reads before deciding
whether a call is affordable. On 2026-08-31 ``list_tasks`` advertised "Returns
task names, headlines, status, and full content" while returning one line per
task, and an agent used shell commands for orientation rather than pay for a
call that would have cost about 2,650 tokens. The description was the defect.

These pin the claim rather than the wording. Every record in the fixtures
carries a long body, so a formatter that regressed to dumping content blows its
budget many times over even though its description still reads correctly.
Asserting on the wording instead would be keyword whack-a-mole.
"""

from datetime import date
from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.journal import (
    format_journal_list,
    list_journal_dates,
    parse_journal_entries,
)
from mcp_server.projects import format_project_list, list_projects
from mcp_server.tasks import (
    format_task_list,
    format_task_search,
    list_tasks,
    search_tasks,
)
from tests.conftest import make_journal_file, make_task, make_tasks_org

# Bodies are built from this so a formatter that emits them is unmistakable in
# the failure, rather than showing up only as a line count that drifted.
BODY_MARKER = "BODY_TEXT_THAT_MUST_NOT_APPEAR_IN_A_LISTING"

# A word that lives only in record bodies, for querying by. Distinct from
# BODY_MARKER because a search echoes its query in the header -- searching
# for the marker itself would trip the marker check on the header line.
BODY_TERM = "quernstone"

RECORD_COUNT = 12
BODY_LINES = 40

# Lines each record is allowed to occupy, by tool. A record's own body runs to
# BODY_LINES, so any budget here fails the moment content is included.
LINE_BUDGET = {
    "list_tasks": 1,
    "search_tasks": 1,
    # One line for the entry, plus the two-line body preview the description
    # promises.
    "list_journal_entries": 3,
    # One line for the project, plus its one-line description preview.
    "list_projects": 2,
}

# Headers, separators, blank lines and any parser warning.
HEADER_ALLOWANCE = 12


def big_body(n: int) -> str:
    """
    A body long enough that including it blows every budget here.

    The first two lines are deliberately unmarked. Some of these tools promise
    a short preview of the body, and those lines are what a preview is allowed
    to contain -- so the marker starts below them. That makes the marker mean
    "this went past the preview it promised" rather than "this showed any body
    text at all", which is what these tools actually guarantee.
    """
    preview = ["a first body line", "a second body line"]
    rest = [
        f"{BODY_MARKER} {BODY_TERM} line {i} of record {n}"
        for i in range(BODY_LINES)
    ]
    return "\n".join(preview + rest)


def check_bounded(output: str, tool: str, records: int) -> None:
    """Check a listing neither embeds bodies nor grows without bound."""
    with check:
        assert BODY_MARKER not in output, (
            f"{tool} included record bodies in a listing. Its description "
            f"says it does not, and callers size their requests on that."
        )

    budget = HEADER_ALLOWANCE + LINE_BUDGET[tool] * records
    actual = len(output.split("\n"))
    with check:
        assert actual <= budget, (
            f"{tool} returned {actual} lines for {records} records, over its "
            f"budget of {budget} ({LINE_BUDGET[tool]} per record plus "
            f"{HEADER_ALLOWANCE} for headers)."
        )


########################################################################
#
@pytest.fixture
def loaded_org_dir(temp_org_dir: Path) -> Path:
    """
    An org directory whose every task and journal entry carries a long body.

    One fixture for both files: the tools under test are all being asked the
    same question, so building the corpus once keeps the checks together.
    """
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(
        make_tasks_org(
            [
                make_task(
                    headline=f"TICKET-{n} Task number {n}",
                    custom_id=f"task-{n}",
                    description=big_body(n),
                )
                for n in range(RECORD_COUNT)
            ],
            [],
        )
    )

    file_date = date(2026, 8, 31)
    entries = [
        f"** {n:02d}:00 Entry number {n} :work:\n{big_body(n)}"
        for n in range(RECORD_COUNT)
    ]
    journal = temp_org_dir / "journal" / file_date.strftime("%Y%m%d")
    journal.write_text(make_journal_file(entries, file_date))

    return temp_org_dir


########################################################################
########################################################################
#
class TestListingsAreBounded:
    """Tests that a listing stays compact however large its records are."""

    ####################################################################
    #
    def test_task_listings_and_searches_return_a_line_per_task(
        self, loaded_org_dir: Path
    ):
        """
        GIVEN: a tasks.org whose every task has a long body
        WHEN:  a section is listed, and separately when a query matches text
               that appears only inside those bodies
        THEN:  each task costs one line and no body text is returned

        Search is the easy case to get wrong: the matching content is exactly
        what a formatter is tempted to echo back.
        """
        check_bounded(
            format_task_list(list_tasks("Tasks"), "Tasks"),
            "list_tasks",
            RECORD_COUNT,
        )

        results = search_tasks(BODY_TERM)
        with check:
            assert len(results.hits) == RECORD_COUNT, "fixture should match all"

        check_bounded(
            format_task_search(results, detail="index"),
            "search_tasks",
            RECORD_COUNT,
        )

    ####################################################################
    #
    def test_journal_and_project_listings_preview_rather_than_dump(
        self, loaded_org_dir: Path, sample_project_files
    ):
        """
        GIVEN: a journal file whose entries have long bodies, and a projects
               directory
        WHEN:  each is listed
        THEN:  every record costs its line plus the short preview its
               description promises, never its whole body

        Both of these do return some body text, which their descriptions call
        a preview. The budget is what keeps a preview from becoming the entry.
        """
        entries = parse_journal_entries(loaded_org_dir / "journal" / "20260831")
        with check:
            assert len(entries) == RECORD_COUNT, "fixture did not parse"

        check_bounded(
            format_journal_list(entries, "2026-08-31"),
            "list_journal_entries",
            len(entries),
        )

        projects = list_projects(None)
        check_bounded(
            format_project_list(projects), "list_projects", len(projects)
        )


########################################################################
########################################################################
#
class TestJournalDateIndex:
    """Tests for the calendar of days that have journal entries."""

    ####################################################################
    #
    def test_only_real_journal_files_count_as_days(self, temp_org_dir: Path):
        """
        GIVEN: a journal directory holding real day files alongside the
               Emacs backups, lock files and .bak files that accumulate
               beside them
        WHEN:  the days with entries are listed
        THEN:  only the real day files are reported, newest first, each with
               its entry count and size

        This scans the directory rather than walking a day at a time, which
        is what makes an unbounded range affordable and what makes the
        filename filter load-bearing. The live journal directory holds 564
        entries for 514 real days, so a loose glob would invent them.
        """
        journal = temp_org_dir / "journal"
        for name in ("20260829", "20260830", "20260831.org"):
            (journal / name).write_text(
                "* day\n** 09:00 First entry\n- a\n** 10:00 Second entry\n- b\n"
            )
        for junk in (
            "20260828~",  # Emacs backup
            "#20260827#",  # Emacs lock file
            "20260826.20260826_120000.bak",  # our own backup
            "notes.txt",  # not a journal file at all
        ):
            (journal / junk).write_text("* day\n** 09:00 Should not count\n")

        dates = list_journal_dates()

        with check:
            assert [d for d, _, _, _ in dates] == [
                "2026-08-31",
                "2026-08-30",
                "2026-08-29",
            ], "newest first, and only real day files"

        for _, entries, lines, chars in dates:
            with check:
                assert entries == 2, "entry count comes from the real parser"
            with check:
                assert lines > 0 and chars > 0, "size hint is populated"

    ####################################################################
    #
    def test_a_date_range_bounds_the_listing(self, temp_org_dir: Path):
        """
        GIVEN: journal files spanning several days
        WHEN:  the listing is bounded by since and until
        THEN:  only days inside the range are returned, inclusive at both ends
        """
        journal = temp_org_dir / "journal"
        for day in ("20260801", "20260815", "20260831"):
            (journal / day).write_text("* day\n** 09:00 Entry\n- a\n")

        bounded = list_journal_dates(since="2026-08-15", until="2026-08-31")

        assert [d for d, _, _, _ in bounded] == ["2026-08-31", "2026-08-15"]
