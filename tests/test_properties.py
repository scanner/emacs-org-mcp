#!/usr/bin/env python
#
"""Test the single canonical format for :PROPERTIES: drawers."""

import pytest

from mcp_server.properties import format_drawer, normalize_drawers
from mcp_server.tasks import create_task, find_task, update_task
from tests.conftest import make_tasks_org

# The one correct rendering: Emacs's own `org-property-format` ("%-10s %s")
# with a three-space body indent.  ":CUSTOM_ID:" is eleven characters and so
# overflows its field by one, exactly as Emacs renders it.
CANONICAL = "\n".join(
    [
        ":PROPERTIES:",
        "   :ID:       DEAD-BEEF",
        "   :CUSTOM_ID: task-sample",
        "   :CREATED:  <2026-08-24 Mon 10:00>",
        ":END:",
    ]
)


########################################################################
########################################################################
#
class TestFormatDrawer:
    """Tests for rendering a drawer from a property mapping."""

    ####################################################################
    #
    def test_renders_canonically_and_in_canonical_order(self):
        """
        GIVEN: properties supplied out of order, including an unknown one
        WHEN:  the drawer is rendered
        THEN:  keys are padded to ten characters, known properties come first
               in canonical order, and unknown ones follow alphabetically
        """
        drawer = format_drawer(
            {
                "ZEBRA": "last",
                "CREATED": "<2026-08-24 Mon 10:00>",
                "CUSTOM_ID": "task-sample",
                "ALPHA": "first-extra",
                "ID": "DEAD-BEEF",
            }
        )

        assert drawer == [
            ":PROPERTIES:",
            "   :ID:       DEAD-BEEF",
            "   :CUSTOM_ID: task-sample",
            "   :CREATED:  <2026-08-24 Mon 10:00>",
            "   :ALPHA:    first-extra",
            "   :ZEBRA:    last",
            ":END:",
        ]

    ####################################################################
    #
    def test_renders_nothing_when_there_are_no_properties(self):
        """
        GIVEN: an empty property mapping
        WHEN:  the drawer is rendered
        THEN:  no lines are produced, rather than a bare empty drawer
        """
        assert format_drawer({}) == []


########################################################################
########################################################################
#
class TestNormalizeDrawers:
    """Tests for rewriting drawers in a file to canonical form."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "drawer",
        [
            pytest.param(CANONICAL, id="already-canonical"),
            pytest.param(
                ":PROPERTIES:\n"
                ":ID:       DEAD-BEEF\n"
                ":CUSTOM_ID:       task-sample\n"
                ":CREATED:       <2026-08-24 Mon 10:00>\n"
                ":END:",
                id="orgmunge-style",
            ),
            pytest.param(
                ":PROPERTIES:\n"
                ":ID: DEAD-BEEF\n"
                ":CUSTOM_ID: task-sample\n"
                ":CREATED: <2026-08-24 Mon 10:00>\n"
                ":END:",
                id="single-space-column-zero",
            ),
            pytest.param(
                ":PROPERTIES:\n"
                "        :ID:    DEAD-BEEF\n"
                "  :CUSTOM_ID:        task-sample\n"
                "\t:CREATED:\t<2026-08-24 Mon 10:00>\n"
                ":END:",
                id="ragged-and-tabbed",
            ),
            pytest.param(
                ":PROPERTIES:\n"
                "   :CREATED:  <2026-08-24 Mon 10:00>\n"
                "   :ID:       DEAD-BEEF\n"
                "   :CUSTOM_ID: task-sample\n"
                ":END:",
                id="wrong-order",
            ),
        ],
    )
    def test_normalizes_every_variant_to_the_same_drawer(self, drawer):
        """
        GIVEN: a drawer in any of the formats found in the wild
        WHEN:  the file is normalized
        THEN:  it becomes the canonical drawer

        The already-canonical case is what proves idempotence: normalizing
        canonical text reproduces it byte for byte, which is what keeps
        well-formed files from churning on every write.
        """
        content = f"** TODO Sample task\n{drawer}\n*** Description\nHi.\n"

        result = normalize_drawers(content)

        assert result == f"** TODO Sample task\n{CANONICAL}\n*** Description\nHi.\n"

    ####################################################################
    #
    def test_normalizes_every_drawer_in_a_file(self):
        """
        GIVEN: a file with several drawers in different formats
        WHEN:  it is normalized
        THEN:  all of them are rewritten
        """
        content = (
            "* Tasks\n"
            "** TODO One\n:PROPERTIES:\n:ID: AAA\n:END:\n"
            "** TODO Two\n:PROPERTIES:\n      :ID:   BBB\n:END:\n"
        )

        result = normalize_drawers(content)

        assert result.count("   :ID:       ") == 2

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content, reason",
        [
            pytest.param(
                "*** Notes\n"
                "#+begin_example\n"
                ":PROPERTIES:\n"
                ":ID: SAMPLE\n"
                ":END:\n"
                "#+end_example\n",
                "a drawer inside a block is a documentation sample",
                id="inside-block",
            ),
            pytest.param(
                "** TODO Task\n:PROPERTIES:\n:ID: AAA\n*** Description\nHi.\n",
                "a drawer with no :END: is not ours to guess at",
                id="unterminated",
            ),
            pytest.param(
                "** TODO Task\n"
                ":PROPERTIES:\n"
                ":ID: AAA\n"
                "this is not a property line\n"
                ":END:\n",
                "a drawer with unrecognised content is left intact",
                id="not-a-drawer",
            ),
        ],
    )
    def test_leaves_content_it_should_not_touch(self, content, reason):
        """
        GIVEN: text that looks like a drawer but must not be rewritten
        WHEN:  the file is normalized
        THEN:  it is returned unchanged

        Rewriting any of these would corrupt the file rather than tidy it.
        """
        assert normalize_drawers(content) == content, reason


########################################################################
########################################################################
#
class TestRoundTrip:
    """Tests that the on-disk format and the API agree."""

    ####################################################################
    #
    def test_disk_and_get_task_agree_and_updates_converge(self, temp_org_dir):
        """
        GIVEN: a task created through the server from a ragged drawer
        WHEN:  it is read back and written straight out again unchanged
        THEN:  get_task's rendering is byte-identical to what is on disk, and
               the task is unchanged apart from the :MODIFIED: timestamp

        Previously three formats were in play -- what was sent, what orgmunge
        wrote, and what get_task rendered -- so a read-modify-write cycle never
        converged and every update churned the drawer.

        NOTE: this asserts on the task, not the whole file. orgmunge also drops
        blank lines between sections on every write, which is tracked
        separately and is not something drawer formatting can fix.
        """
        tasks_file = temp_org_dir / "tasks.org"
        tasks_file.write_text(make_tasks_org([], []))

        create_task(
            "Tasks",
            "** TODO Sample task\n"
            ":PROPERTIES:\n"
            ":ID: DEAD-BEEF\n"
            "        :CUSTOM_ID:   task-sample\n"
            ":END:\n"
            "*** Description\nHello.\n",
        )

        returned = find_task("task-sample")[0].content

        # What the API hands back is exactly what the file holds.
        assert "   :ID:       DEAD-BEEF" in returned
        assert returned in tasks_file.read_text()

        # Feeding it straight back changes nothing but the timestamp.
        update_task("task-sample", returned)
        after = find_task("task-sample")[0].content

        def without_modified(text: str) -> str:
            return "\n".join(
                line for line in text.split("\n") if ":MODIFIED:" not in line
            )

        assert without_modified(after) == without_modified(returned)
        assert after in tasks_file.read_text()
