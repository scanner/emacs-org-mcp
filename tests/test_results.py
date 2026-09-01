#!/usr/bin/env python
#
"""
Tests for the shared result envelope.

These cover the envelope in isolation -- paging, detail levels, size hints and
the guarantee that a warning cannot be paged past. How a task or a journal
entry becomes a Record is the adapter's business and is tested with those
types.

Each test renders a page once and then makes every check that page can answer,
using ``pytest_check`` so one wrong line does not hide the rest. A rendered
page is a single artefact with several properties, and splitting those
properties across a test each buys nothing but a longer test run to read.
"""

import pytest
from pytest_check import check

from mcp_server.results import (
    DEFAULT_LIMIT,
    MAX_SNIPPET_LINES,
    MAX_TITLE,
    Record,
    format_size,
    render,
    snippet_lines,
)


def make_records(n: int, body: str = "") -> list[Record]:
    """Build n uniform records, optionally each carrying the same body."""
    return [
        Record(
            ref=f"rec-{i}",
            prefix="TODO",
            title=f"Record number {i}",
            suffix=f"(rec-{i})",
            content=body,
        )
        for i in range(n)
    ]


########################################################################
########################################################################
#
class TestResultEnvelope:
    """Tests for how a page of results bounds and describes itself."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content, expected",
        [
            pytest.param("", "", id="empty-body-has-no-hint"),
            pytest.param("one line", "[1L 8c]", id="characters-under-1k"),
            pytest.param("x" * 2500, "[1L 2.5k]", id="characters-over-1k"),
            pytest.param("a\nb\nc", "[3L 5c]", id="counts-lines"),
        ],
    )
    def test_size_is_reported_as_lines_and_characters(self, content, expected):
        """
        GIVEN: a record body
        WHEN:  its size is rendered
        THEN:  lines and characters are both shown, and an empty body shows
               nothing

        Lines predict how a record reads and characters predict what it costs,
        so a caller deciding whether to fetch it in full needs both.
        """
        assert format_size(*Record(ref="r", content=content).size) == expected

    ####################################################################
    #
    def test_snippets_show_why_a_record_matched(self):
        """
        GIVEN: record bodies, a query, and bodies that match it many times or
               not at all
        WHEN:  snippets are taken
        THEN:  matching lines are returned with a line of context either side,
               no record contributes more than MAX_SNIPPET_LINES, and having
               nothing to show yields nothing rather than a placeholder

        The cap is what keeps the level bounded: without it a record matching
        a common word contributes a line per match.
        """
        with check:
            assert snippet_lines(
                "alpha\nbravo\nNEEDLE here\ndelta\necho", ["needle"]
            ) == ["bravo", "NEEDLE here", "delta"]

        flood = "\n".join(f"match {i}" for i in range(200))
        with check:
            assert len(snippet_lines(flood, ["match"])) == MAX_SNIPPET_LINES

        for content, query_terms, why in [
            ("some text", [], "no terms"),
            ("", ["needle"], "no content"),
            ("some text", ["absent"], "no match"),
        ]:
            with check:
                assert snippet_lines(content, query_terms) == [], why

        # A ranked search matches on stems, so the snippet must too: matching
        # the raw query instead shows nothing for a record that ranked well.
        with check:
            assert snippet_lines("Compaction of the bucket", ["compact"]) == [
                "Compaction of the bucket"
            ], "a stem must find the word it came from"

    ####################################################################
    #
    def test_a_bounded_page_describes_itself_and_the_next_call(self):
        """
        GIVEN: more results than fit on one page
        WHEN:  the first page is rendered
        THEN:  only the limit is shown, the total is stated, and the next call
               is spelled out with the tool name and the offset to use

        The next call is given in words because an agent reading this cannot
        be relied on to infer a pagination convention. A caller that names no
        limit is bounded by DEFAULT_LIMIT rather than handed the whole corpus.
        """
        output = render(
            make_records(120), tool="search_tasks", header="Tasks", limit=50
        )

        for expected in (
            "120 results, showing 1-50",
            "70 more. Next: call search_tasks with offset=50",
            "Record number 49",
        ):
            with check:
                assert expected in output

        with check:
            assert "Record number 50" not in output, "page limit not applied"

        unbounded = render(
            make_records(5000), tool="search_journal", header="J"
        )
        with check:
            assert f"showing 1-{DEFAULT_LIMIT}" in unbounded

    ####################################################################
    #
    @pytest.mark.parametrize(
        "total, offset, expected, absent",
        [
            pytest.param(
                60, 50, "showing 51-60", "Next:", id="last-page-offers-no-more"
            ),
            pytest.param(
                10,
                200,
                "10 results, but offset 200 is past the end",
                "Record number",
                id="offset-past-the-end-says-so",
            ),
            pytest.param(
                0, 0, "no results", "Next:", id="nothing-matched-says-so"
            ),
        ],
    )
    def test_page_boundaries_are_stated_not_implied(
        self, total, offset, expected, absent
    ):
        """
        GIVEN: a request landing on the last page, past the end, or on an
               empty result set
        WHEN:  the page is rendered
        THEN:  the response says which of those happened, and offers a next
               call only when one exists

        An empty page is otherwise indistinguishable from no matches at all.
        """
        output = render(
            make_records(total),
            tool="search_tasks",
            header="Tasks",
            offset=offset,
        )

        with check:
            assert expected in output
        with check:
            assert absent not in output

    ####################################################################
    #
    def test_detail_levels_control_what_reaches_the_page(self):
        """
        GIVEN: records carrying bodies, and a query those bodies match
        WHEN:  the same records are rendered at each detail level
        THEN:  index shows no body at all, full shows every body, snippet
               shows only the matching lines, and snippet asked for without a
               query falls back to index

        Index keeps a listing's cost predictable from the record count alone.
        Snippet exists because an index line says which record matched but
        never why, so search would otherwise always cost a second, blind
        fetch. The fallback avoids making a parameter's validity depend on
        which tool it was passed to.
        """
        records = make_records(2, body="prelude\nthe NEEDLE line\ncoda")

        def page(**kwargs) -> str:
            return render(
                records, tool="search_tasks", header="Tasks", **kwargs
            )

        with check:
            assert "NEEDLE" not in page(detail="index"), "index leaked a body"

        with check:
            assert page(detail="full").count("the NEEDLE line") == 2

        with check:
            assert "> the NEEDLE line" in page(
                detail="snippet", query_terms=["needle"]
            )

        no_query = page(detail="snippet")
        with check:
            assert "NEEDLE" not in no_query, "snippet without a query leaked"
        with check:
            assert "Record number 0" in no_query, "fallback dropped results"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "total, offset",
        [
            pytest.param(120, 0, id="first-page"),
            pytest.param(120, 50, id="middle-page"),
            pytest.param(120, 100, id="last-page"),
            pytest.param(0, 0, id="no-results-at-all"),
        ],
    )
    def test_a_warning_reaches_the_caller_on_every_page(self, total, offset):
        """
        GIVEN: a result set with a warning attached, read at any page
        WHEN:  that page is rendered
        THEN:  the warning appears, above the results

        The report of tasks the org parser cannot see is a data-loss
        guarantee. A warning rendered after the results, or only on the final
        page, is one a caller reading page one never sees -- so it belongs to
        the envelope rather than to whatever appends to the output. No results
        is precisely when it matters most: the tasks may be missing rather
        than absent.
        """
        warning = "WARNING: 2 tasks are invisible to the parser"
        output = render(
            make_records(total),
            tool="list_tasks",
            header="Tasks",
            offset=offset,
            warnings=[warning],
        )

        with check:
            assert warning in output
        with check:
            assert output.index(warning) < output.index("Tasks --")

    ####################################################################
    #
    def test_trimming_a_long_title_keeps_what_a_follow_up_needs(self):
        """
        GIVEN: a record whose title is far longer than a line allows
        WHEN:  it is rendered
        THEN:  the title is trimmed while the status and the reference survive

        The reference is what a follow-up call needs, so it must never be the
        part dropped to save room.
        """
        output = render(
            [
                Record(
                    ref="task-important",
                    prefix="TODO",
                    title="x" * (MAX_TITLE * 2),
                    suffix="(task-important)",
                )
            ],
            tool="list_tasks",
            header="Tasks",
        )

        for expected in ("(task-important)", "TODO", "…"):
            with check:
                assert expected in output
        with check:
            assert "x" * (MAX_TITLE * 2) not in output, "title not trimmed"
