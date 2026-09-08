#!/usr/bin/env python
#
"""
Tests for archiving a task out of tasks.org.

Emacs does the move, so ``run_org_archive`` is the one part that needs a live
Emacs and the one part replaced here. The fake really relocates the heading --
out of tasks.org, into a ``_archive`` sibling -- because everything these
tests are about happens either side of that: what may be archived, whether the
result verifies, what is repaired afterwards, and what a failure leaves behind.
A fake that only reported success would leave all of it unexercised.

``manual_test_archive.py`` is what covers the elisp against a real Emacs.
"""

# system imports
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

# 3rd party imports
import pytest
from pytest_mock import MockerFixture

# project imports
from mcp_server.archiving import (
    ArchiveError,
    archive_tasks,
    format_archive_report,
    resolve_targets,
    run_org_archive,
)
from mcp_server.config import Config
from mcp_server.linking import link_task_to_project
from mcp_server.tasks import scan_section_headings, scan_task_identities
from mcp_server.utils import quote_elisp
from tests.conftest import TasksFileInfo

# =============================================================================
# The Emacs Seam, Faked
# =============================================================================

# A level-1 or level-2 heading, which is where a task's subtree ends.
SUBTREE_END_RE = re.compile(r"^\*{1,2} \S")


###############################################################################
#
def move_subtree(tasks_file: Path, custom_id: str) -> Path:
    """
    Move a task's subtree into an archive file, as org would.

    Args:
        tasks_file: The tasks file to take the task out of
        custom_id: The ``:CUSTOM_ID:`` of the task to move

    Returns:
        The archive file the subtree was written to.

    Note:
        Stands in for ``org-archive-subtree``. It does not have to reproduce
        org's context properties or its heading levels -- what the production
        code needs from it is a task that has genuinely left one file and
        genuinely arrived in the other, since that is what verification reads.
    """
    lines = tasks_file.read_text(encoding="utf-8").split("\n")
    start = _heading_line_of(lines, custom_id)

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if SUBTREE_END_RE.match(lines[index])
        ),
        len(lines),
    )

    subtree = lines[start:end]
    remaining = lines[:start] + lines[end:]

    archive = tasks_file.with_name(f"{tasks_file.name}_archive")
    existing = archive.read_text(encoding="utf-8") if archive.exists() else ""

    archive.write_text(
        existing + "\n".join(subtree).rstrip("\n") + "\n", encoding="utf-8"
    )
    tasks_file.write_text("\n".join(remaining), encoding="utf-8")

    return archive


###############################################################################
#
def _heading_line_of(lines: list[str], custom_id: str) -> int:
    """
    Find the heading line of the task carrying a ``:CUSTOM_ID:``.

    Args:
        lines: The file's lines
        custom_id: The id to look for

    Returns:
        The index of the task's heading line.

    Raises:
        AssertionError: If no task in the file carries that id, which in a
            test means the fixture and the test disagree.
    """
    heading = -1

    for index, line in enumerate(lines):
        if SUBTREE_END_RE.match(line):
            heading = index
        if line.strip() == f":CUSTOM_ID: {custom_id}":
            assert heading >= 0, f"{custom_id} has no heading above it"
            return heading

    raise AssertionError(f"no task in this file has :CUSTOM_ID: {custom_id}")


###############################################################################
#
@pytest.fixture
def emacs(mocker: MockerFixture) -> Callable[..., None]:
    """
    Replace the Emacs call with a fake move, and hand back the knob for it.

    Returns:
        A callable taking ``also_removes`` -- extra ``:CUSTOM_ID:``s the fake
        should delete on its way past, which is how a write that loses a task
        it was not asked to touch is simulated -- and ``removes``, which when
        False leaves the task where it is.
    """

    def _install(
        also_removes: list[str] | None = None, removes: bool = True
    ) -> None:
        def _fake(tasks_file: Path, custom_id: str) -> Path:
            archive = move_subtree(tasks_file, custom_id)

            for extra in also_removes or []:
                move_subtree(tasks_file, extra)

            if not removes:
                # Put the task back, as an Emacs that reported success
                # without moving anything would leave it.
                text = archive.read_text(encoding="utf-8")
                tasks_file.write_text(
                    tasks_file.read_text(encoding="utf-8") + text,
                    encoding="utf-8",
                )

            return archive

        mocker.patch("mcp_server.archiving.run_org_archive", side_effect=_fake)

    _install()
    return _install


# =============================================================================
# Resolving What To Archive
# =============================================================================


###############################################################################
###############################################################################
#
class TestResolvingTargets:
    """What may be archived, and what has to be refused."""

    @pytest.mark.parametrize(
        "identifier",
        ["task-jira-1234", "JIRA-1234", "authentication"],
        ids=["custom-id", "ticket-id", "headline-substring"],
    )
    def test_an_identifier_naming_one_task_resolves(
        self, sample_tasks_file: TasksFileInfo, identifier: str
    ):
        """
        GIVEN: A tasks.org where one task matches an identifier
         WHEN: Tasks are resolved for archiving
         THEN: That task is the target, however it was named -- by
               :CUSTOM_ID:, by ticket ID, or by a substring of its headline
        """
        targets, already = resolve_targets([identifier])

        assert [task.custom_id for task in targets] == ["task-jira-1234"]
        assert already == []

    def test_an_ambiguous_identifier_refuses_the_whole_call(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An identifier that is a substring of more than one headline
         WHEN: Those tasks are archived
         THEN: Nothing is archived, and the error names every candidate, so
               the caller can pick one instead of having one picked for them
          AND: The tasks are all still in tasks.org
        """
        # "JIRA" is in two of the fixture's headlines, one active and one
        # completed. Archiving is a removal, so first-match-wins -- which is
        # how reading a task resolves -- would take one of them and report
        # success.
        with pytest.raises(ArchiveError) as error:
            archive_tasks(["JIRA"])

        assert "matches 2 tasks" in str(error.value)
        assert "Fix authentication bug" in str(error.value)
        assert "Old completed task" in str(error.value)

        identities = scan_task_identities(sample_tasks_file["path"].read_text())
        assert set(sample_tasks_file["task_names"]) <= set(identities)

    def test_an_unknown_identifier_refuses_the_whole_call(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: A list of tasks to archive where one of them does not exist
         WHEN: The list is archived
         THEN: Nothing is archived at all, because a partly-archived list is
               not the list that was confirmed
        """
        with pytest.raises(ArchiveError) as error:
            archive_tasks(["task-jira-1234", "task-does-not-exist"])

        assert "task-does-not-exist' matches no task" in str(error.value)
        assert "task-jira-1234" in scan_task_identities(
            sample_tasks_file["path"].read_text()
        )

    def test_a_task_named_twice_is_archived_once(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: One task named two ways in the same call, by ticket ID and by
               :CUSTOM_ID:
         WHEN: The call is archived
         THEN: The task is archived once, since two names for one task are one
               instruction
        """
        report = archive_tasks(["JIRA-1234", "task-jira-1234"])

        assert [result.task_id for result in report.archived] == [
            "task-jira-1234"
        ]
        assert report.failure is None

    def test_an_already_archived_task_is_reported_not_refused(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: A task that has already been archived
         WHEN: It is archived again
         THEN: The call reports it as already archived and writes nothing,
               rather than refusing because the task is no longer in
               tasks.org -- so re-running a list that partly succeeded
               completes it
        """
        archive_tasks(["task-jira-1234"])
        before = sample_tasks_file["path"].read_text()

        report = archive_tasks(["task-jira-1234"])

        assert report.archived == []
        assert [name for name, _ in report.already] == ["task-jira-1234"]
        assert sample_tasks_file["path"].read_text() == before

    def test_nothing_named_is_refused(self, sample_tasks_file: TasksFileInfo):
        """
        GIVEN: An empty list of tasks
         WHEN: It is archived
         THEN: The call is refused, rather than reporting a successful archive
               of nothing
        """
        with pytest.raises(ArchiveError, match="No tasks named"):
            archive_tasks([])


# =============================================================================
# Archiving
# =============================================================================


###############################################################################
###############################################################################
#
class TestArchivingATask:
    """What archiving leaves behind, in both files."""

    def test_the_task_leaves_tasks_org_and_arrives_in_the_archive(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: A task in tasks.org
         WHEN: It is archived
         THEN: It is gone from tasks.org and present in the archive file,
               which is where the tool reports it went
          AND: Every other task and every section heading is untouched, since
               archiving one task is all that was asked for
        """
        tasks_file = sample_tasks_file["path"]
        sections_before = scan_section_headings(tasks_file.read_text())

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is None
        result = report.archived[0]
        assert result.archive_file.name == "tasks.org_archive"
        assert ":CUSTOM_ID: task-jira-1234" in result.archive_file.read_text()

        remaining = scan_task_identities(tasks_file.read_text())
        assert "task-jira-1234" not in remaining
        assert set(remaining) == {
            "task-new-feature",
            "task-review",
            "task-jira-4321",
        }
        assert scan_section_headings(tasks_file.read_text()) == sections_before

    def test_the_pre_image_is_removed_once_the_archive_verifies(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: A task being archived
         WHEN: The archive verifies
         THEN: The pre-image taken before Emacs ran is removed, so the
               timestamped copies do not accumulate one per archive
        """
        archive_tasks(["task-jira-1234"])

        # The pre-image is backup_file's timestamped copy. write_file's own
        # `tasks.org.bak` is a different artifact and is expected to be there.
        stale = [
            path.name
            for path in sample_tasks_file["path"].parent.iterdir()
            if re.fullmatch(r"tasks\.\d{8}_\d{6}\.bak", path.name)
        ]
        assert stale == []

    def test_a_task_without_a_custom_id_is_given_one_first(
        self, temp_org_dir: Path, emacs: Callable[..., None]
    ):
        """
        GIVEN: A task carrying no :CUSTOM_ID:, as tasks predating the
               convention do
         WHEN: It is archived
         THEN: It is given one and archived by it, since Emacs is never handed
               a headline to match on
          AND: The result says an id was assigned, so the caller can see the
               property appear in the file's history
        """
        (temp_org_dir / "tasks.org").write_text(
            "* Tasks\n\n"
            "** TODO An old task from before ids\n\n"
            "*** Description\n\nSomething once mattered here.\n\n"
            "* Completed Tasks\n"
        )

        report = archive_tasks(["An old task"])

        result = report.archived[0]
        assert result.custom_id_assigned is True
        assert result.task_id == "task-an-old-task-from-before-ids"
        assert f":CUSTOM_ID: {result.task_id}" in (
            result.archive_file.read_text()
        )

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
            "stops-before-to-the",
            "keeps-inner",
            "all-stopwords",
        ],
    )
    def test_a_minted_id_does_not_end_mid_phrase(
        self,
        temp_org_dir: Path,
        emacs: Callable[..., None],
        headline: str,
        expected: str,
    ):
        """
        GIVEN: A task with no :CUSTOM_ID: whose headline runs longer than an
               id should
         WHEN: It is archived and an id is minted from the headline
         THEN: The id is the leading words of the headline, stopping short of
               a trailing preposition or article, so it reads as a phrase
               rather than as a sentence cut off mid-way
          AND: One of those words inside the phrase is kept, since there it is
               part of what the task is called
          AND: A headline that is nothing but such words still yields an id,
               since every task must have one
        """
        (temp_org_dir / "tasks.org").write_text(
            f"* Tasks\n\n** TODO {headline}\n\n* Completed Tasks\n"
        )

        report = archive_tasks([headline])

        assert report.archived[0].task_id == expected

    def test_the_high_level_checklist_item_goes_with_it(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An archived task that has a line in the High Level Tasks
               checklist
         WHEN: It is archived
         THEN: The checklist line is removed too, so the checklist does not
               keep tracking work that has left the file
        """
        report = archive_tasks(["task-jira-1234"])

        assert report.archived[0].checklist_end == "removed"
        assert "Fix authentication bug" not in (
            sample_tasks_file["path"].read_text()
        )

    def test_archiving_changes_nothing_else_about_the_file(
        self, temp_org_dir: Path, emacs: Callable[..., None]
    ):
        """
        GIVEN: A tasks.org with the blank lines a person put between its
               sections and tasks
         WHEN: A task is archived, checklist line and all
         THEN: Every remaining line is exactly as it was, so the change to the
               file is the archived task and nothing else. Archiving is a move,
               and a move that reformats the file it leaves buries itself in a
               diff over everything
        """
        tasks_file = temp_org_dir / "tasks.org"
        tasks_file.write_text(
            "* High Level Tasks (in order) [0/2]\n"
            "- [ ] Keep this one\n"
            "- [ ] Archive this one\n"
            "\n"
            "* Tasks\n"
            "\n"
            "** TODO GH-1 Keep this one\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-1\n"
            ":END:\n"
            "\n"
            "*** Description\n"
            "\n"
            "Still here.\n"
            "\n"
            "** TODO GH-2 Archive this one\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-2\n"
            ":END:\n"
            "\n"
            "* Completed Tasks\n"
        )

        report = archive_tasks(["task-gh-2"])

        assert report.archived[0].checklist_end == "removed"
        assert tasks_file.read_text() == (
            "* High Level Tasks (in order) [0/2]\n"
            "- [ ] Keep this one\n"
            "\n"
            "* Tasks\n"
            "\n"
            "** TODO GH-1 Keep this one\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-1\n"
            ":END:\n"
            "\n"
            "*** Description\n"
            "\n"
            "Still here.\n"
            "\n"
            "* Completed Tasks\n"
        )

    def test_a_checklist_without_a_matching_line_is_reported(
        self, temp_org_dir: Path, emacs: Callable[..., None]
    ):
        """
        GIVEN: An archived task whose description does not appear in the High
               Level Tasks checklist
         WHEN: It is archived
         THEN: The result says the checklist line was not found, rather than
               reporting a removal that did not happen -- the description is
               derived from the headline, so a differently-worded checklist
               is a silent no-op otherwise
        """
        # The checklist tracks the same work in different words, which is
        # what a hand-written checklist looks like.
        (temp_org_dir / "tasks.org").write_text(
            "* High Level Tasks (in order) [0/1]\n"
            "- [ ] Sort out the login mess\n\n"
            "* Tasks\n\n"
            "** TODO GH-9 Fix authentication bug\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-9\n"
            ":END:\n\n"
            "* Completed Tasks\n"
        )

        report = archive_tasks(["task-gh-9"])

        assert report.archived[0].checklist_end == "not found"
        assert (
            "Sort out the login mess"
            in (temp_org_dir / "tasks.org").read_text()
        )

    def test_an_archive_outside_the_search_roots_is_reported(
        self,
        sample_tasks_file: TasksFileInfo,
        tmp_path: Path,
        config_factory: Callable[[Config], None],
        emacs: Callable[..., None],
    ):
        """
        GIVEN: An org configured to archive somewhere the server does not
               search
         WHEN: A task is archived there
         THEN: The archive succeeds, and the result says the task can no
               longer be found by search_org -- org owns where archives go,
               and this is the consequence the caller has to know about
        """
        # Point the search roots somewhere else entirely, which is what a
        # datetree archive outside the org directory amounts to.
        elsewhere = tmp_path / "not-searched"
        elsewhere.mkdir()
        config_factory(
            Config(
                org_dir=sample_tasks_file["path"].parent,
                search_roots=[elsewhere],
                ediff_approval=False,
                git_autocommit=False,
            )
        )

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is None
        assert "outside the search roots" in "\n".join(report.archived[0].notes)


# =============================================================================
# The Project End
# =============================================================================


###############################################################################
###############################################################################
#
class TestTheProjectEnd:
    """What happens to a project that was pointing at the task."""

    def test_the_project_link_is_repointed_at_the_archive(
        self,
        sample_tasks_file: TasksFileInfo,
        sample_project_files: dict,
        emacs: Callable[..., None],
    ):
        """
        GIVEN: A task linked to a project, so the project's Related Tasks
               section holds a link into tasks.org
         WHEN: The task is archived
         THEN: The link is rewritten to point at the archive file, so the
               project keeps its record of work that happened instead of
               holding a link that resolves to nothing
          AND: The link keeps its #task-id anchor, which is what linking
               recognises an existing link by, so nothing appends a second one
        """
        link_task_to_project("task-jira-1234", "booklore")
        project_file = sample_project_files["projects_dir"] / "booklore.org"

        report = archive_tasks(["task-jira-1234"])

        assert report.archived[0].project_end == "repointed"
        content = project_file.read_text()
        assert content.count("::#task-jira-1234]") == 1
        assert "tasks.org_archive::#task-jira-1234]" in content

    def test_a_project_that_cannot_be_repaired_does_not_fail_the_archive(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An archived task whose :PROJECT: names a project that is not
               there any more
         WHEN: It is archived
         THEN: The archive still succeeds, and the result says the project end
               was not repaired -- once the task has moved, no later repair
               may report the archive as having failed
        """
        # A :PROJECT: nothing resolves, which is what a deleted or renamed
        # project file leaves behind on its tasks.
        content = sample_tasks_file["path"].read_text()
        sample_tasks_file["path"].write_text(
            content.replace(
                "   :CUSTOM_ID: task-jira-1234",
                "   :CUSTOM_ID: task-jira-1234\n   :PROJECT:  project-gone",
            )
        )

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is None
        assert report.archived[0].project_end == (
            "project 'project-gone' not found"
        )

    def test_a_repair_that_cannot_be_written_does_not_fail_the_archive(
        self,
        sample_tasks_file: TasksFileInfo,
        sample_project_files: dict,
        mocker: MockerFixture,
        emacs: Callable[..., None],
    ):
        """
        GIVEN: A linked task whose project file cannot be written -- read-only,
               a full disk, a permission change
         WHEN: The task is archived
         THEN: The archive still succeeds, since the task has moved and no
               later step may report otherwise
          AND: The result says the project end was NOT repaired, and why, so
               the link still pointing into tasks.org is visible rather than
               being left to be discovered
        """
        link_task_to_project("task-jira-1234", "booklore")
        mocker.patch(
            "mcp_server.archiving.write_file",
            side_effect=OSError("Read-only file system"),
        )

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is None
        assert report.archived[0].project_end == (
            "NOT repaired: Read-only file system"
        )

    def test_a_task_with_no_project_says_so(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An archived task belonging to no project
         WHEN: It is archived
         THEN: The result says there was no project end to repair
        """
        report = archive_tasks(["task-jira-1234"])

        assert report.archived[0].project_end == "no project"


# =============================================================================
# Failure
# =============================================================================


###############################################################################
###############################################################################
#
class TestWhenTheArchiveDoesNotVerify:
    """The guarantees that replace write_tasks_org's write guard."""

    def test_a_write_that_loses_another_task_is_rolled_back(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An archive that also removes a task it was not asked to touch
         WHEN: A task is archived
         THEN: tasks.org is restored, so the task that was not named is back
          AND: The archived copy is left alone -- a task in two places can be
               reconciled by hand and a task in neither cannot
          AND: The error names the pre-image and the buffer to revert, since
               Emacs is still holding what it wrote
        """
        tasks_file = sample_tasks_file["path"]
        before = tasks_file.read_text()
        emacs(also_removes=["task-review"])

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is not None
        assert "task-review" in report.failure
        assert ".bak" in report.failure
        assert "revert" in report.failure.lower()

        identities = scan_task_identities(tasks_file.read_text())
        assert set(identities) == set(scan_task_identities(before))

        archive = tasks_file.with_name("tasks.org_archive")
        assert ":CUSTOM_ID: task-jira-1234" in archive.read_text()

    def test_a_task_that_did_not_move_is_reported_as_such(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: An Emacs that reports success without the task leaving
               tasks.org
         WHEN: A task is archived
         THEN: The failure says the task is still there, rather than trusting
               the report of the process that was supposed to move it
        """
        emacs(removes=False)

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is not None
        assert "still in tasks.org" in report.failure

    def test_a_batch_stops_at_the_first_failure(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: Several tasks to archive, where archiving goes wrong
         WHEN: The batch runs
         THEN: It stops at the failure rather than repeating it for every
               remaining task
          AND: It reports what was archived before the failure, so the caller
               knows how far the run got
        """
        emacs(removes=False)

        report = archive_tasks(
            ["task-jira-1234", "task-new-feature", "task-review"]
        )

        assert report.failure is not None
        assert report.archived == []
        assert "task-new-feature" in scan_task_identities(
            sample_tasks_file["path"].read_text()
        )


# =============================================================================
# The Emacs Call Itself
# =============================================================================


###############################################################################
###############################################################################
#
class TestTheEmacsCall:
    """How the call to Emacs fails, and what it refuses to send."""

    def test_archiving_without_emacs_is_a_hard_failure(
        self,
        sample_tasks_file: TasksFileInfo,
        mocker: MockerFixture,
    ):
        """
        GIVEN: An installation where emacsclient cannot be found
         WHEN: A task is archived
         THEN: The call fails and says Emacs is what does the archiving,
               rather than falling back to some other behaviour: org's
               org-archive-subtree is the only implementation there is
          AND: tasks.org is unchanged
        """
        mocker.patch(
            "mcp_server.archiving.get_emacsclient_path", return_value=None
        )
        before = sample_tasks_file["path"].read_text()

        report = archive_tasks(["task-jira-1234"])

        assert report.failure is not None
        assert "running Emacs" in report.failure
        assert sample_tasks_file["path"].read_text() == before

    def test_an_error_from_emacs_is_passed_on(
        self, temp_org_dir: Path, mocker: MockerFixture
    ):
        """
        GIVEN: An Emacs that refuses the archive, as it does when the
               tasks.org buffer holds unsaved changes
         WHEN: The archive is attempted
         THEN: The failure carries Emacs' own words, which say what to do
               about it
        """
        mocker.patch(
            "mcp_server.archiving.get_emacsclient_path",
            return_value="/usr/bin/emacsclient",
        )
        mocker.patch(
            "mcp_server.archiving.ensure_elisp_loaded", return_value=True
        )
        mocker.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="*ERROR*: Buffer tasks.org has unsaved changes",
            ),
        )

        with pytest.raises(ArchiveError, match="unsaved changes"):
            run_org_archive(temp_org_dir / "tasks.org", "task-anything")

    def test_a_slow_emacs_does_not_hang_the_call(
        self, temp_org_dir: Path, mocker: MockerFixture
    ):
        """
        GIVEN: An Emacs that does not answer, as one waiting in the
               minibuffer does not
         WHEN: The archive is attempted
         THEN: The call gives up and says to check Emacs, and to check whether
               the task moved before archiving it again
        """
        mocker.patch(
            "mcp_server.archiving.get_emacsclient_path",
            return_value="/usr/bin/emacsclient",
        )
        mocker.patch(
            "mcp_server.archiving.ensure_elisp_loaded", return_value=True
        )
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("emacsclient", 30),
        )

        with pytest.raises(ArchiveError, match="did not answer"):
            run_org_archive(temp_org_dir / "tasks.org", "task-anything")

    @pytest.mark.parametrize(
        "answer",
        ['""', "nil", '"relative/path_archive"'],
        ids=["empty", "nil", "relative"],
    )
    def test_an_unusable_answer_stops_the_operation(
        self, temp_org_dir: Path, mocker: MockerFixture, answer: str
    ):
        """
        GIVEN: An Emacs that exits cleanly without naming an archive file
         WHEN: The archive is attempted
         THEN: The call fails rather than carrying on, since the answer is
               what decides which file gets verified and committed
        """
        mocker.patch(
            "mcp_server.archiving.get_emacsclient_path",
            return_value="/usr/bin/emacsclient",
        )
        mocker.patch(
            "mcp_server.archiving.ensure_elisp_loaded", return_value=True
        )
        mocker.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=answer, stderr=""
            ),
        )

        with pytest.raises(ArchiveError, match="did not say where"):
            run_org_archive(temp_org_dir / "tasks.org", "task-anything")

    def test_an_id_that_could_be_elisp_is_refused(
        self, temp_org_dir: Path, emacs: Callable[..., None]
    ):
        """
        GIVEN: A task whose :CUSTOM_ID: is not the shape this server writes
         WHEN: It is archived
         THEN: The call is refused, because the id is passed to Emacs as
               elisp source and only a narrow shape can be sent safely
        """
        (temp_org_dir / "tasks.org").write_text(
            "* Tasks\n\n"
            "** TODO Suspicious task\n"
            ":PROPERTIES:\n"
            '   :CUSTOM_ID: id") (delete-file "/etc/passwd\n'
            ":END:\n\n"
            "* Completed Tasks\n"
        )

        report = archive_tasks(["Suspicious task"])

        assert report.failure is not None
        assert "not the shape this server writes" in report.failure

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("task-gh-28", '"task-gh-28"'),
            ('say "hi"', '"say \\"hi\\""'),
            ("back\\slash", '"back\\\\slash"'),
        ],
        ids=["plain", "quotes", "backslash"],
    )
    def test_values_sent_to_emacs_stay_values(self, value: str, expected: str):
        """
        GIVEN: A string being passed to Emacs, such as a path or an id
         WHEN: It is rendered for --eval
         THEN: It comes back as an elisp string literal that reads as exactly
               that string, since everything sent to Emacs is source it will
               evaluate
        """
        assert quote_elisp(value) == expected


# =============================================================================
# Reporting
# =============================================================================


###############################################################################
###############################################################################
#
class TestReporting:
    """What the caller is told."""

    def test_the_report_names_both_ends_and_where_it_went(
        self,
        sample_tasks_file: TasksFileInfo,
        sample_project_files: dict,
        emacs: Callable[..., None],
    ):
        """
        GIVEN: A task archived out of tasks.org
         WHEN: The result is rendered
         THEN: It names the task, the file it went to, and what happened at
               the project and checklist ends, so a half-repaired archive is
               visible rather than being reported as a plain success
        """
        link_task_to_project("task-jira-1234", "booklore")

        output = format_archive_report(archive_tasks(["task-jira-1234"]))

        assert "✓ Archived task-jira-1234" in output
        assert "tasks.org_archive" in output
        assert "project:     repointed" in output
        assert "checklist:   removed" in output

    def test_a_failure_is_reported_under_what_succeeded(
        self, sample_tasks_file: TasksFileInfo, emacs: Callable[..., None]
    ):
        """
        GIVEN: A batch that archived one task and then failed
         WHEN: The result is rendered
         THEN: The failure comes after the successes, so a caller reading it
               can tell which tasks it still applies to
        """
        report = archive_tasks(["task-jira-1234"])
        report.failure = "Emacs refused the next one"

        output = format_archive_report(report)

        assert output.index("✓ Archived") < output.index("✗ Stopped")
