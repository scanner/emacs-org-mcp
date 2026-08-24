#!/usr/bin/env python
#
"""
Regression tests for the tasks.org data-loss bug.

An update_task call once destroyed the task that followed its target. These
tests pin the guarantees that make that structurally impossible: no write may
remove a task it was not asked to touch, tasks the parser cannot see are
reported rather than silently omitted, and the previous file is always
recoverable from a .bak.

Two distinct corruptions can hide a task from the parser, and both are
exercised here:

- **indented heading** — a leading space makes org read ``** TODO Task`` as
  body text, folding the whole task into its predecessor's subtree. This is
  the mechanism of the 2026-08-23 incident.
- **phantom heading** — orgmunge does not honour ``#+begin_src`` fencing, so a
  ``* Tasks`` line inside a block becomes a real level-1 heading and
  re-parents every task after it.
"""

import contextlib
from pathlib import Path

import pytest

from mcp_server.tasks import (
    create_task,
    find_section,
    find_task,
    find_unparsed_tasks,
    format_task_list,
    get_org,
    list_tasks,
    move_task,
    scan_task_identities,
    search_tasks,
    update_task,
    write_tasks_org,
)
from tests.conftest import make_task, make_tasks_org

# A task big enough to exercise the size/churn conditions of the original
# incident: many level-4 subsections, a source block and a table.
BIG_TASK = "\n".join(
    [
        "** TODO Big task with lots of structure",
        ":PROPERTIES:",
        "   :CUSTOM_ID: task-big",
        ":END:",
        "*** Description",
        "A task with the shape that triggered the original data loss.",
        *[
            line
            for n in range(1, 12)
            for line in (
                f"**** Subsection {n}",
                f"Body text for subsection {n}.",
                "#+begin_src python",
                f"def step_{n}():",
                f"    return {n}",
                "#+end_src",
                "| col a | col b |",
                "|-------+-------|",
                f"| row   | {n}     |",
            )
        ],
        "*** Task items [0/1]",
        "- [ ] Something",
    ]
)

ORDINARY_TASK = make_task(
    headline="Ordinary follower",
    custom_id="task-follower",
    description="This task must survive updates to the one before it.",
)

# The victim's heading carries a single leading space, so org folds it into
# the preceding task.
INDENTED_VICTIM_FILE = (
    "* Tasks\n"
    "** TODO Preceding task\n"
    ":PROPERTIES:\n   :CUSTOM_ID: task-preceding\n:END:\n"
    "*** Notes\nSome body.\n"
    " ** TODO Victim task\n"
    ":PROPERTIES:\n   :CUSTOM_ID: task-victim\n:END:\n"
    "*** Description\nUNIQUE_VICTIM_STRING\n"
    "* Completed Tasks\n"
)

# The unescaped "* Tasks" inside the source block parses as a real level-1
# heading, which re-parents the task that follows it.
PHANTOM_HEADING_FILE = (
    "* Tasks\n"
    "** TODO Preceding task\n"
    ":PROPERTIES:\n   :CUSTOM_ID: task-preceding\n:END:\n"
    "*** Notes\n#+begin_src org\n* Tasks\n#+end_src\n"
    "** TODO Victim task\n"
    ":PROPERTIES:\n   :CUSTOM_ID: task-victim\n:END:\n"
    "*** Description\nUNIQUE_VICTIM_STRING\n"
    "* Completed Tasks\n"
)


########################################################################
#
@pytest.fixture
def big_then_ordinary(temp_org_dir: Path) -> Path:
    """A tasks.org holding the big structured task followed by a plain one."""
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(make_tasks_org([BIG_TASK, ORDINARY_TASK], []))
    return tasks_file


########################################################################
#
@pytest.fixture(
    params=[
        pytest.param(INDENTED_VICTIM_FILE, id="indented-heading"),
        pytest.param(PHANTOM_HEADING_FILE, id="phantom-heading"),
    ]
)
def hidden_victim(request, temp_org_dir: Path) -> Path:
    """A tasks.org whose second task is invisible to the org parser."""
    tasks_file = temp_org_dir / "tasks.org"
    tasks_file.write_text(request.param)
    return tasks_file


########################################################################
########################################################################
#
class TestScanTaskIdentities:
    """Tests for the raw-text task scanner the write guard relies on."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content, expected",
        [
            pytest.param(
                "* Tasks\n"
                "** TODO A\n:PROPERTIES:\n   :CUSTOM_ID: task-a\n:END:\n"
                "** DONE B\n:PROPERTIES:\n   :CUSTOM_ID: task-b\n:END:\n",
                ["task-a", "task-b"],
                id="ordinary-tasks",
            ),
            pytest.param(
                "* Tasks\n"
                "** TODO A\n:PROPERTIES:\n   :CUSTOM_ID: task-a\n:END:\n"
                "*** Notes\n#+begin_example\n** TODO Quoted\n#+end_example\n",
                ["task-a"],
                id="ignores-quoted-heading",
            ),
            pytest.param(
                INDENTED_VICTIM_FILE,
                ["task-preceding", "task-victim"],
                id="counts-indented-heading",
            ),
            pytest.param(
                "* Tasks\n** TODO Untitled task\n",
                ["headline:Untitled task"],
                id="falls-back-to-headline",
            ),
        ],
    )
    def test_identifies_every_task_in_the_raw_text(self, content, expected):
        """
        GIVEN: tasks.org content, possibly with a corrupted heading
        WHEN:  the raw text is scanned
        THEN:  every real task is found, in file order, and quoted samples are
               not counted

        The scanner must not use orgmunge: its whole job is to notice tasks the
        parser has lost track of, including ones pushed off column zero.
        """
        assert scan_task_identities(content) == expected


########################################################################
########################################################################
#
class TestUpdatePreservesOtherTasks:
    """Regression tests for the task-that-follows deletion bug."""

    ####################################################################
    #
    def test_updating_a_big_task_leaves_the_next_task_intact(
        self, big_then_ordinary
    ):
        """
        GIVEN: a very large task followed by an ordinary one
        WHEN:  the large task is rewritten via update_task
        THEN:  both tasks still parse and the follower is byte-identical

        This is the shape of the incident that lost 76 lines.
        """
        before = find_task("task-follower")[0].content

        update_task(
            "task-big",
            "** TODO Big task with lots of structure\n"
            ":PROPERTIES:\n   :CUSTOM_ID: task-big\n:END:\n"
            "*** Description\nRewritten from scratch.\n",
        )

        assert [t.custom_id for t in list_tasks("Tasks")] == [
            "task-big",
            "task-follower",
        ]
        assert find_task("task-follower")[0].content == before

    ####################################################################
    #
    def test_a_malformed_entry_leaves_the_file_untouched(
        self, big_then_ordinary
    ):
        """
        GIVEN: an update whose entry puts a subsection at ** level
        WHEN:  update_task is called
        THEN:  it raises and the file is byte-for-byte unchanged

        Previously the parser kept only the first ** heading, so everything
        after the stray one was discarded while the call reported success.
        Which entries are rejected is covered in test_validation.py; this pins
        that a rejection never half-writes.
        """
        original = big_then_ordinary.read_text()

        with pytest.raises(ValueError, match="Invalid task structure"):
            update_task(
                "task-big",
                "** TODO Big task with lots of structure\n"
                "*** Description\nRewritten.\n"
                "** Notes\nWould have been silently dropped.\n",
            )

        assert big_then_ordinary.read_text() == original

    ####################################################################
    #
    def test_updating_a_predecessor_cannot_destroy_a_hidden_task(
        self, hidden_victim
    ):
        """
        GIVEN: a task hidden from the parser by either corruption
        WHEN:  the task before it is rewritten via update_task
        THEN:  the hidden task's content survives

        The two corruptions survive by different routes, and only the survival
        is guaranteed: under the indented heading the victim sits inside the
        predecessor's subtree and the guard has to actively refuse the write
        (asserted below); under the phantom heading it sits in a separate
        subtree and is simply never touched.
        """
        with contextlib.suppress(ValueError):
            update_task(
                "task-preceding",
                "** TODO Preceding task\n"
                ":PROPERTIES:\n   :CUSTOM_ID: task-preceding\n:END:\n"
                "*** Notes\nRewritten.\n",
            )

        assert "UNIQUE_VICTIM_STRING" in hidden_victim.read_text()

    ####################################################################
    #
    def test_the_guard_refuses_the_incident_write(self, temp_org_dir: Path):
        """
        GIVEN: a task absorbed into its predecessor by an indented heading
        WHEN:  that predecessor is rewritten via update_task
        THEN:  the write is refused, naming the task it would have destroyed

        This is the exact write that destroyed 76 lines on 2026-08-23.
        """
        tasks_file = temp_org_dir / "tasks.org"
        tasks_file.write_text(INDENTED_VICTIM_FILE)

        with pytest.raises(ValueError, match="task-victim"):
            update_task(
                "task-preceding",
                "** TODO Preceding task\n"
                ":PROPERTIES:\n   :CUSTOM_ID: task-preceding\n:END:\n"
                "*** Notes\nRewritten.\n",
            )

        assert tasks_file.read_text() == INDENTED_VICTIM_FILE


########################################################################
########################################################################
#
class TestWriteGuard:
    """Tests for the guard that refuses task-destroying writes."""

    ####################################################################
    #
    def test_refuses_a_write_that_drops_an_untargeted_task(
        self, big_then_ordinary
    ):
        """
        GIVEN: an org tree from which a task was removed behind the guard's back
        WHEN:  it is written with no task exempted
        THEN:  the write is refused, naming the task, and the file is unchanged

        This is the backstop: it holds no matter *why* a task went missing.
        """
        original = big_then_ordinary.read_text()
        org = get_org()
        section = find_section(org, "Tasks")
        section.remove_child(list(section.children)[-1])

        with pytest.raises(ValueError, match="task-follower"):
            write_tasks_org(org, summary="test")

        assert big_then_ordinary.read_text() == original

    ####################################################################
    #
    def test_allows_removing_the_task_it_was_told_about(
        self, big_then_ordinary
    ):
        """
        GIVEN: an org tree with the targeted task removed
        WHEN:  it is written with that task named as the target
        THEN:  the write succeeds

        update_task legitimately removes and re-adds its target.
        """
        org = get_org()
        section = find_section(org, "Tasks")
        section.remove_child(list(section.children)[-1])

        write_tasks_org(org, summary="test", target="task-follower")

        assert [t.custom_id for t in list_tasks("Tasks")] == ["task-big"]

    ####################################################################
    #
    def test_ordinary_operations_pass_the_guard(self, big_then_ordinary):
        """
        GIVEN: a normal tasks.org
        WHEN:  a task is created and another is moved between sections
        THEN:  neither trips the guard and both tasks survive
        """
        create_task("Tasks", make_task("Brand new", "task-new"))
        move_task("task-follower", "Tasks", "Completed Tasks")

        assert [t.custom_id for t in list_tasks("Tasks")] == [
            "task-big",
            "task-new",
        ]
        assert [t.custom_id for t in list_tasks("Completed Tasks")] == [
            "task-follower"
        ]


########################################################################
########################################################################
#
class TestHiddenTaskDetection:
    """Tests that tasks invisible to the parser are reported, not omitted."""

    ####################################################################
    #
    def test_the_parser_really_cannot_see_the_task(self, hidden_victim):
        """
        GIVEN: a file corrupted so a task is hidden from the parser
        WHEN:  it is listed and searched
        THEN:  the task is absent from listings, and searching for text unique
               to its body does not return it

        This characterises the failure the detection below exists to surface.
        Under the indented-heading corruption the search returns the task that
        absorbed it, which is exactly the reported symptom.
        """
        assert [t.custom_id for t in list_tasks("Tasks")] == ["task-preceding"]

        hits = [t.custom_id for t in search_tasks("UNIQUE_VICTIM_STRING")]

        assert "task-victim" not in hits

    ####################################################################
    #
    def test_hidden_tasks_are_reported_in_listings(self, hidden_victim):
        """
        GIVEN: a file containing a task the parser cannot see
        WHEN:  the task list is formatted
        THEN:  the output warns about it instead of silently omitting it
        """
        assert find_unparsed_tasks() == ["task-victim"]

        output = format_task_list(list_tasks("Tasks"), "Tasks")

        assert "WARNING" in output
        assert "task-victim" in output

    ####################################################################
    #
    def test_not_found_errors_mention_hidden_tasks(self, hidden_victim):
        """
        GIVEN: a task that is in the file but hidden from the parser
        WHEN:  it is looked up
        THEN:  the error distinguishes "hidden" from "never existed"
        """
        with pytest.raises(ValueError, match="not visible to the parser"):
            find_task("task-victim")

    ####################################################################
    #
    def test_quoting_org_syntax_does_not_hide_later_tasks(
        self, temp_org_dir: Path
    ):
        """
        GIVEN: a task entry quoting org syntax in a source block
        WHEN:  it is created
        THEN:  the sample is comma-escaped, so it never becomes a real heading

        This is the prevention half: the phantom-heading corruption above can
        no longer be introduced through the server.
        """
        (temp_org_dir / "tasks.org").write_text(make_tasks_org([], []))

        create_task(
            "Tasks",
            "** TODO Quotes org syntax\n"
            ":PROPERTIES:\n   :CUSTOM_ID: task-quoting\n:END:\n"
            "*** Notes\n#+begin_src org\n* Tasks\n#+end_src\n",
        )
        create_task("Tasks", make_task("Follower", "task-after"))

        assert ",* Tasks" in (temp_org_dir / "tasks.org").read_text()
        assert find_unparsed_tasks() == []


########################################################################
########################################################################
#
class TestBackupRetention:
    """Tests that the previous file version survives a write."""

    ####################################################################
    #
    def test_previous_contents_are_kept_as_bak(self, big_then_ordinary):
        """
        GIVEN: an existing tasks.org
        WHEN:  a task is created
        THEN:  a .bak alongside it holds the pre-write contents

        Recovery must not depend on an Emacs autosave happening to exist.
        """
        original = big_then_ordinary.read_text()

        create_task("Tasks", make_task("Brand new", "task-new"))

        assert big_then_ordinary.with_suffix(".org.bak").read_text() == original
