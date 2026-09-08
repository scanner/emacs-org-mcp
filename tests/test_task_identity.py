#!/usr/bin/env python
#
"""
Tests for a task's :CUSTOM_ID:, which is what everything else addresses it by.

The invariant these pin down is that a task has a stable identity: given when
it is created, repaired wherever it is found missing, and never a shape that
breaks the two places it ends up -- an org link anchor, and elisp source when
archiving drives Emacs.
"""

# system imports
from pathlib import Path

# 3rd party imports
import pytest

# project imports
from mcp_server.tasks import (
    create_task,
    ensure_custom_id,
    find_task,
    mint_custom_id,
    scan_task_identities,
    update_task,
    validate_custom_id,
)
from tests.conftest import TasksFileInfo, make_task, make_tasks_org

# =============================================================================
# Fixtures
# =============================================================================


###############################################################################
#
@pytest.fixture
def task_with_an_id(temp_org_dir: Path) -> Path:
    """One task, carrying the id its headline would mint."""
    (temp_org_dir / "tasks.org").write_text(
        make_tasks_org(
            [make_task("Rewrite the importer", "task-rewrite-the-importer")],
            [],
        )
    )
    return temp_org_dir


# =============================================================================
# Minting
# =============================================================================


###############################################################################
###############################################################################
#
class TestMintingAnId:
    """What a minted id is built from."""

    @pytest.mark.parametrize(
        "headline,expected",
        [
            ("Fix the auth bug", "task-fix-the-auth-bug"),
            ("GH-123 Fix the auth bug", "task-fix-the-auth-bug"),
            (
                "[[https://host/browse/ABC-1][ABC-1]] Rewrite the importer",
                "task-rewrite-the-importer",
            ),
            (
                "[ABC-1] [[https://host/browse/ABC-1][ABC-1]] Hash-range work",
                "task-hash-range-work",
            ),
        ],
        ids=["plain", "ticket-prefix", "ticket-as-link", "bracketed-and-link"],
    )
    def test_an_id_is_words_about_the_task(
        self, empty_tasks_file: Path, headline: str, expected: str
    ):
        """
        GIVEN: A headline, which may carry its ticket as a bare prefix, as an
               org link, or as both
         WHEN: An id is minted for it
         THEN: The id is built from the words describing the task, with the
               link's target and the ticket left out -- neither is words about
               the task, and a link's URL would otherwise become the id
          AND: One ticket routinely covers several tasks, so the ticket does
               not identify one of them and never becomes the id
        """
        assert mint_custom_id(headline) == expected

    @pytest.mark.parametrize(
        "headline,expected",
        [
            (
                "Spike: SQL+Rego+Data POC in posture_rules",
                "task-spike-sql-rego-data-poc",
            ),
            (
                "Move the ingest worker to the new queue",
                "task-move-the-ingest-worker",
            ),
            ("Retire the shim", "task-retire-the-shim"),
            ("In and of the", "task-in"),
        ],
        ids=[
            "stops-before-in",
            "stops-before-to",
            "nothing-to-trim",
            "all-stopwords",
        ],
    )
    def test_an_id_does_not_end_mid_phrase(
        self, empty_tasks_file: Path, headline: str, expected: str
    ):
        """
        GIVEN: A headline longer than an id should be
         WHEN: An id is minted for it
         THEN: The id stops short of a trailing preposition or conjunction, so
               it reads as a phrase rather than as a sentence cut off
          AND: One of those words inside the phrase is kept, since there it is
               part of what the task is called
          AND: A headline that is nothing but such words still yields an id,
               because every task must have one
        """
        assert mint_custom_id(headline) == expected

    def test_an_id_is_unique_against_the_file(self, temp_org_dir: Path):
        """
        GIVEN: A task already carrying the id a new task's headline would mint
         WHEN: An id is minted for the new task
         THEN: It is given a numeric suffix instead, since two tasks sharing
               an id would make both unfindable
        """
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org(
                [
                    make_task(
                        "Rewrite the importer", "task-rewrite-the-importer"
                    )
                ],
                [],
            )
        )

        assert mint_custom_id("Rewrite the importer") == (
            "task-rewrite-the-importer-2"
        )

    def test_an_id_is_unique_against_a_task_that_left(self, temp_org_dir: Path):
        """
        GIVEN: An id held by a task that has left tasks.org for an archive
         WHEN: An id is minted for a task whose headline would produce it
         THEN: The archived id is avoided, because uniqueness has to hold
               across every file an id can travel to -- an archived task is
               not in tasks.org and its id is still spoken for
          AND: Nothing has to hand the archives to the minting: every mint
               site gets this, not only the one that knows about archiving
        """
        (temp_org_dir / "tasks.org").write_text(make_tasks_org([], []))
        (temp_org_dir / "tasks.org_archive").write_text(
            "* Archived tasks\n"
            + make_task("Rewrite the importer", "task-rewrite-the-importer")
        )

        assert mint_custom_id("Rewrite the importer") == (
            "task-rewrite-the-importer-2"
        )


# =============================================================================
# The Shape Rule
# =============================================================================


###############################################################################
###############################################################################
#
class TestTheShapeRule:
    """Which ids this server will act on at all."""

    @pytest.mark.parametrize(
        "custom_id",
        ["task-gh-28", "task-rb-1.2", "task_underscored", "T4"],
        ids=["ordinary", "dotted", "underscored", "terse"],
    )
    def test_an_ordinary_id_is_accepted(self, custom_id: str):
        """
        GIVEN: An id of letters, digits, dots, dashes or underscores
         WHEN: It is validated
         THEN: It is accepted, since it survives both an org link anchor and
               being passed to Emacs
        """
        validate_custom_id(custom_id)

    @pytest.mark.parametrize(
        "custom_id",
        [
            'id") (delete-file "/etc/passwd',
            "has space",
            "colon:id",
            "",
            "-lead",
        ],
        ids=["elisp", "space", "colon", "empty", "leading-dash"],
    )
    def test_an_id_that_changes_meaning_elsewhere_is_refused(
        self, custom_id: str
    ):
        """
        GIVEN: An id carrying a character that means something where the id
               is used -- a quote in elisp source, a colon in a link anchor,
               whitespace in either
         WHEN: It is validated
         THEN: It is refused, naming what an id may contain

        Enforced wherever an id is used rather than only where it is minted,
        because an id can arrive by hand.
        """
        with pytest.raises(ValueError, match="not a usable"):
            validate_custom_id(custom_id)


# =============================================================================
# Creating
# =============================================================================


###############################################################################
###############################################################################
#
class TestCreatingATask:
    """The invariant is established when a task is created."""

    def test_an_entry_without_an_id_is_given_one(self, empty_tasks_file: Path):
        """
        GIVEN: A task entry whose drawer carries no :CUSTOM_ID:
         WHEN: The task is created
         THEN: It is given one minted from its headline, so the server cannot
               create a task that nothing is able to address
          AND: The task is findable by that id afterwards, which is the whole
               point of having it
        """
        create_task("Tasks", "** TODO Rewrite the importer")

        task, _, _, _ = find_task("task-rewrite-the-importer")
        assert task.headline == "Rewrite the importer"

    def test_an_entry_with_an_id_keeps_it(self, empty_tasks_file: Path):
        """
        GIVEN: A task entry that names its own :CUSTOM_ID:
         WHEN: The task is created
         THEN: That id is kept, since a caller who chose one has said what the
               task should be called
        """
        create_task(
            "Tasks",
            "** TODO Rewrite the importer\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-importer-rewrite\n"
            ":END:",
        )

        task, _, _, _ = find_task("task-importer-rewrite")
        assert task.headline == "Rewrite the importer"

    def test_an_entry_with_an_unusable_id_is_refused(
        self, empty_tasks_file: Path
    ):
        """
        GIVEN: A task entry naming a :CUSTOM_ID: that would not survive a link
               anchor or a trip through Emacs
         WHEN: The task is created
         THEN: The create is refused rather than writing a task that later
               operations would choke on
        """
        with pytest.raises(ValueError, match="not a usable"):
            create_task(
                "Tasks",
                "** TODO Rewrite the importer\n"
                ":PROPERTIES:\n"
                "   :CUSTOM_ID: not usable:here\n"
                ":END:",
            )


# =============================================================================
# Repairing
# =============================================================================


###############################################################################
###############################################################################
#
class TestRepairingATaskThatHasNone:
    """What happens to the tasks written before the invariant held."""

    def test_a_task_is_given_an_id_without_disturbing_the_others(
        self, temp_org_dir: Path
    ):
        """
        GIVEN: A tasks.org holding a task with no :CUSTOM_ID: alongside others
         WHEN: That task is given one
         THEN: It carries the minted id and is findable by it
          AND: Every other task is still there, because the write goes through
               the same guard as any other and the task's identity in the raw
               file changes with it -- from its headline to its new id
        """
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org(
                [
                    make_task("Keep me", "task-keep-me"),
                    "** TODO An old task from before ids",
                    make_task("Keep me too", "task-keep-me-too"),
                ],
                [],
            )
        )

        task, _, _, _ = find_task("An old task")
        task, assigned = ensure_custom_id(task)

        assert assigned is True
        assert task.custom_id == "task-an-old-task-from-before-ids"

        identities = scan_task_identities(
            (temp_org_dir / "tasks.org").read_text()
        )
        assert set(identities) == {
            "task-keep-me",
            "task-keep-me-too",
            "task-an-old-task-from-before-ids",
        }

    def test_a_task_that_has_one_is_left_alone(
        self, sample_tasks_file: TasksFileInfo
    ):
        """
        GIVEN: A task that already carries a :CUSTOM_ID:
         WHEN: Its identity is ensured
         THEN: Nothing is written and the existing id is reported, so this is
               safe to call on any task before an operation that needs one
        """
        before = sample_tasks_file["path"].read_text()

        task, _, _, _ = find_task("task-jira-1234")
        task, assigned = ensure_custom_id(task)

        assert assigned is False
        assert task.custom_id == "task-jira-1234"
        assert sample_tasks_file["path"].read_text() == before

    def test_an_ambiguous_headline_is_refused(self, temp_org_dir: Path):
        """
        GIVEN: Two tasks with no :CUSTOM_ID: whose headlines cannot be told
               apart by substring
         WHEN: One of them is given an id
         THEN: The call is refused rather than writing the property to
               whichever task happened to come first
        """
        (temp_org_dir / "tasks.org").write_text(
            make_tasks_org(
                [
                    "** TODO Review the plan",
                    "** TODO Review the plan again",
                ],
                [],
            )
        )

        task, _, _, _ = find_task("Review the plan")

        with pytest.raises(ValueError, match="names more than one task"):
            ensure_custom_id(task)


# =============================================================================
# Keeping
# =============================================================================


###############################################################################
###############################################################################
#
class TestAnIdOutlivesAnEdit:
    """An id names the task for as long as the task exists."""

    def test_a_replacement_that_omits_the_drawer_keeps_the_id(
        self, task_with_an_id: Path
    ):
        """
        GIVEN: A task carrying a :CUSTOM_ID:, and a replacement entry for it
               written without a :PROPERTIES: drawer
         WHEN: The task is updated
         THEN: It still carries the same id, because an update replaces the
               content a caller wrote and not the properties the server keeps
          AND: No new id is minted for it, which would leave every project
               linking to it pointing at an anchor that no longer resolves
        """
        update_task(
            "task-rewrite-the-importer",
            "** TODO Rewrite the importer, revised scope",
        )

        task, _, _, _ = find_task("task-rewrite-the-importer")

        assert task.custom_id == "task-rewrite-the-importer"
        assert task.headline == "Rewrite the importer, revised scope"
        assert scan_task_identities(
            (task_with_an_id / "tasks.org").read_text()
        ) == ["task-rewrite-the-importer"]
