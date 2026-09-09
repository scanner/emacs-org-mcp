#!/usr/bin/env python
#
"""
Tests that the factories build what production builds.

Everything else in the suite reads a file one of these wrote, so a factory
that emits a shape production never writes makes those tests agree with each
other and with nothing else. Whether the output *parses* needs no test here:
several hundred tests parse it on every run and say so loudly when it stops.
What needs a test is the formatting the factories reproduce by hand, since
that agreement is what a reader is trusting when they take a fixture as an
example of a real file.
"""

# system imports
from datetime import date

# project imports
from mcp_server.properties import format_drawer
from tests.conftest import make_journal_file, make_task

# =============================================================================
# The shapes a factory copies rather than calls
# =============================================================================


###############################################################################
#
def test_a_task_fixture_carries_a_canonical_drawer():
    """
    GIVEN: A task written by the factory the suite files its fixtures with
     WHEN: Its :PROPERTIES: drawer is compared with the one the server writes
     THEN: They are identical, so a fixture is an example of a real file and
           a test asserting on drawer text is asserting on the real format

    ``make_task`` builds the drawer by hand rather than calling
    ``format_drawer``, which is what lets the two drift. They agree today;
    this is what says so tomorrow.
    """
    drawer = format_drawer(
        {"ID": "C5045326-9DC8-4F1E-A895-8895720DD928", "CUSTOM_ID": "task-x"}
    )
    fixture = make_task(
        headline="X",
        custom_id="task-x",
        task_id="C5045326-9DC8-4F1E-A895-8895720DD928",
    ).split("\n")

    assert fixture[1 : 1 + len(drawer)] == drawer


###############################################################################
#
def test_a_journal_fixture_carries_the_date_heading_the_parser_looks_for():
    """
    GIVEN: A journal file written by the factory
     WHEN: Its first line is read
     THEN: It is the ``* YYYY-MM-DD`` heading the format specifies, which is
           what the parser keys the file's date on
    """
    assert make_journal_file([], date(2025, 12, 22)).split("\n")[0] == (
        "* 2025-12-22"
    )
