#!/usr/bin/env python
#
"""
Regression tests for headline metadata lost when a task is re-rendered.

A headline carries more than stars, a keyword and a title. Org writes it as::

    STARS TODO [#PRIORITY] title [cookie] :tags:

:func:`heading_to_org_string` rebuilt only stars, keyword, title and tags, so
every re-render silently deleted the progress cookie and the priority.

That made a read-modify-write cycle destructive rather than convergent, which
is the shape of the bug that actually bites: ``get_task`` hands back content
with the cookie already gone, and feeding that straight to ``update_task`` --
what an agent does whenever it edits a task -- writes the loss to disk. It is
invisible at the moment it happens, because nothing errors and the diff looks
like an ordinary edit.

Measured on 2026-08-31 before the fix: 109 of 139 ``*** Task items`` headings
in the live tasks.org had lost their cookie, against 30 that still had one.

The write path itself was never at fault. ``str(org)`` renders cookies and
priorities correctly; only our own re-render dropped them.
"""

from pathlib import Path

import pytest
from orgmunge import Org
from pytest_check import check

from mcp_server.tasks import (
    create_task,
    find_task,
    heading_to_org_string,
    update_task,
)

# A task whose subsections carry every headline component org supports, so a
# rebuild that forgets one is caught by name rather than by a diff.
DECORATED_TASK = """** TODO Task with decorated subsections
:PROPERTIES:
   :CUSTOM_ID: task-decorated
:END:

*** Description
Body text.

*** Task items [1/3]
- [X] one
- [ ] two
- [ ] three

*** [#A] An urgent subsection
More body text.

*** Review progress [50%] :review:later:
Still more.
"""


########################################################################
########################################################################
#
class TestHeadlineComponentsSurviveReRendering:
    """Tests that re-rendering a heading is lossless."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "headline",
        [
            pytest.param("*** Just a heading", id="plain"),
            pytest.param("*** Task items [1/3]", id="progress-cookie"),
            pytest.param("*** Progress [50%]", id="percent-cookie"),
            pytest.param("*** [#A] Important subsection", id="priority"),
            pytest.param("*** [#B] Items [0/2]", id="priority-and-cookie"),
            pytest.param(
                "*** Task items [2/5] :urgent:work:", id="cookie-and-tags"
            ),
            pytest.param("*** Tagged only :work:", id="tags-only"),
        ],
    )
    def test_a_heading_renders_back_to_what_it_was(self, headline: str):
        """
        GIVEN: a subsection heading carrying any combination of priority,
               progress cookie and tags
        WHEN:  it is parsed and rendered back to org
        THEN:  the headline is byte-identical to what was parsed

        Anything dropped here is deleted from the file on the next write, with
        no error and a diff that reads like an ordinary edit.
        """
        source = (
            "* Tasks\n"
            "** TODO A task\n"
            ":PROPERTIES:\n   :CUSTOM_ID: task-a\n:END:\n"
            f"{headline}\nbody text\n"
        )
        subsection = (
            Org(source, from_file=False)
            .root.children[0]
            .children[0]
            .children[0]
        )

        rendered = heading_to_org_string(subsection).split("\n")[0]

        assert rendered == headline

    ####################################################################
    #
    def test_a_read_modify_write_cycle_does_not_erode_a_task(
        self, temp_org_dir: Path
    ):
        """
        GIVEN: a task whose subsections carry cookies, a priority and tags
        WHEN:  it is read with get_task and written straight back with
               update_task, the way an agent edits a task
        THEN:  the file still holds every cookie, priority and tag, and
               repeating the cycle changes nothing further

        This is the destructive path. get_task returning less than the file
        holds is not itself visible, but feeding that back writes the loss to
        disk, so each edit erodes the task a little further.
        """
        tasks_file = temp_org_dir / "tasks.org"
        tasks_file.write_text("* Tasks\n\n* Completed Tasks\n")
        create_task("Tasks", DECORATED_TASK)

        update_task("task-decorated", find_task("task-decorated")[0].content)
        on_disk = tasks_file.read_text()

        for expected in ("[1/3]", "[#A]", "[50%]", ":review:later:"):
            with check:
                assert expected in on_disk, (
                    f"{expected} was deleted by a read-modify-write cycle"
                )

        # The first write is expected to differ: it stamps :MODIFIED:. The
        # guarantee is that every cycle after it is a fixed point, so an
        # unattended sequence of edits cannot drift.
        settled = find_task("task-decorated")[0].content
        update_task("task-decorated", settled)

        with check:
            assert find_task("task-decorated")[0].content == settled
