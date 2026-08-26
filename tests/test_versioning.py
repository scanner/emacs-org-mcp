#!/usr/bin/env python
#
"""Test git versioning of org files the server modifies."""

from collections.abc import Callable
from pathlib import Path

import pytest
from git import Repo

from mcp_server.config import Config, global_state
from mcp_server.tasks import create_task, update_task
from mcp_server.utils import write_file
from mcp_server.versioning import commit_file, ensure_backups_ignored
from tests.conftest import make_task, make_tasks_org


########################################################################
#
@pytest.fixture
def org_repo(
    tmp_path: Path, config_factory: Callable[[Config], None]
) -> tuple[Path, Repo]:
    """An org directory that is a git repo with one commit, autocommit on."""
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    repo = Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")

    tasks_file = tmp_path / "tasks.org"
    tasks_file.write_text(
        make_tasks_org([make_task("Existing task", "task-existing")], [])
    )
    repo.git.add("--", str(tasks_file))
    repo.git.commit("-m", "Initial commit")

    config_factory(
        Config(
            org_dir=tmp_path,
            journal_dir=journal_dir,
            projects_dir=projects_dir,
            ediff_approval=False,
            git_autocommit=True,
        )
    )
    return (tmp_path, repo)


########################################################################
########################################################################
#
class TestCommitFile:
    """Tests for committing a single org file."""

    ####################################################################
    #
    def test_commits_a_file_git_has_never_seen(self, org_repo):
        """
        GIVEN: a brand new org file in a subdirectory, untracked
        WHEN:  it is committed
        THEN:  it is staged first, so the commit succeeds

        A pathspec commit alone will not match an untracked path. This also
        covers finding the repository by searching upward from a subdirectory.
        """
        org_dir, repo = org_repo
        new_file = org_dir / "projects" / "booklore.org"
        new_file.write_text("* Booklore  :project:\n")

        assert commit_file(new_file, "create project booklore") is True

        assert "projects/booklore.org" in repo.head.commit.stats.files

    ####################################################################
    #
    @pytest.mark.parametrize(
        "scenario",
        [
            pytest.param("unchanged", id="content-identical-to-head"),
            pytest.param("disabled", id="autocommit-disabled"),
            pytest.param("merging", id="merge-in-progress"),
            pytest.param("no-repo", id="not-a-repository"),
        ],
    )
    def test_declines_to_commit(self, org_repo, tmp_path_factory, scenario):
        """
        GIVEN: a reason not to commit -- nothing changed, versioning turned
               off, a git operation underway, or no repository at all
        WHEN:  a commit is attempted
        THEN:  it reports False and creates no commit, without raising

        None of these may ever fail the org write that preceded them: the file
        on disk is already correct.
        """
        org_dir, repo = org_repo
        before = repo.head.commit.hexsha
        target = org_dir / "tasks.org"

        match scenario:
            case "unchanged":
                pass  # leave the file exactly as committed
            case "disabled":
                target.write_text(target.read_text() + "\n* Extra\n")
                global_state.config.git_autocommit = False
            case "merging":
                target.write_text(target.read_text() + "\n* Extra\n")
                (Path(repo.git_dir) / "MERGE_HEAD").write_text(before + "\n")
            case "no-repo":
                target = tmp_path_factory.mktemp("plain") / "tasks.org"
                target.write_text("* Tasks\n")

        assert commit_file(target, "update tasks") is False
        assert repo.head.commit.hexsha == before

    ####################################################################
    #
    def test_leaves_other_staged_work_alone(self, org_repo):
        """
        GIVEN: an unrelated file the user has staged but not committed
        WHEN:  an org file is committed
        THEN:  only the org file is committed and the other stays staged

        This is why a pathspec commit is used instead of index.commit(), which
        would sweep up whatever the user happened to have staged.
        """
        org_dir, repo = org_repo
        unrelated = org_dir / "notes.txt"
        unrelated.write_text("work in progress\n")
        repo.git.add("--", str(unrelated))

        tasks_file = org_dir / "tasks.org"
        tasks_file.write_text(tasks_file.read_text() + "\n* Extra\n")
        commit_file(tasks_file, "update tasks")

        assert list(repo.head.commit.stats.files) == ["tasks.org"]
        assert "notes.txt" in repo.git.diff("--cached", "--name-only")

    ####################################################################
    #
    def test_sweeps_in_changes_made_outside_the_server(self, org_repo):
        """
        GIVEN: an org file edited outside the server since the last commit
        WHEN:  the server later commits that same file
        THEN:  the outside edit is included

        Intentional: no version of the file goes unrecorded, even when the
        server was not the one that changed it.
        """
        org_dir, repo = org_repo
        tasks_file = org_dir / "tasks.org"
        tasks_file.write_text(
            tasks_file.read_text() + "\nEdited in Emacs directly.\n"
        )

        commit_file(tasks_file, "update tasks")

        assert "Edited in Emacs directly." in repo.git.show("HEAD:tasks.org")


########################################################################
########################################################################
#
class TestWriteFileIntegration:
    """Tests that org writes commit automatically."""

    ####################################################################
    #
    def test_task_operations_produce_readable_history(self, org_repo):
        """
        GIVEN: an org repository
        WHEN:  a task is created and then updated through the normal tools
        THEN:  each operation leaves its own commit, newest first, and the
               working tree is left clean

        This covers the whole chain: tool -> write_file -> commit.
        """
        org_dir, repo = org_repo

        create_task("Tasks", make_task("New thing", "task-new"))
        update_task(
            "task-new",
            "** TODO New thing, revised\n"
            ":PROPERTIES:\n   :CUSTOM_ID: task-new\n:END:\n"
            "*** Description\nRevised.\n",
        )

        messages = [c.message.strip() for c in repo.iter_commits(max_count=2)]

        assert messages == [
            "emacs-org-mcp: update task task-new",
            "emacs-org-mcp: create task task-new",
        ]
        assert not repo.is_dirty(path=str(org_dir / "tasks.org"))

    ####################################################################
    #
    def test_a_write_without_a_summary_does_not_commit(self, org_repo):
        """
        GIVEN: an org repository
        WHEN:  write_file is called with no summary
        THEN:  the file is written but nothing is committed

        Callers opt in to versioning by describing the change.
        """
        org_dir, repo = org_repo
        before = repo.head.commit.hexsha

        write_file(org_dir / "tasks.org", "* Tasks\n")

        assert (org_dir / "tasks.org").read_text() == "* Tasks\n"
        assert repo.head.commit.hexsha == before

    ####################################################################
    #
    def test_backups_are_kept_out_of_the_repo(self, org_repo):
        """
        GIVEN: an org repository
        WHEN:  a write creates a .bak alongside the org file
        THEN:  .gitignore excludes it, so it is never committed or synced
        """
        org_dir, repo = org_repo

        write_file(org_dir / "tasks.org", "* Tasks\n", summary="rewrite tasks")

        assert (org_dir / "tasks.org.bak").exists()
        assert "*.bak" in (org_dir / ".gitignore").read_text()
        assert "tasks.org.bak" not in repo.git.status("--porcelain")

    ####################################################################
    #
    def test_an_existing_gitignore_is_not_clobbered(self, org_repo):
        """
        GIVEN: a .gitignore the user already maintains
        WHEN:  the backup rule is added twice
        THEN:  the existing content is preserved and the rule appears once
        """
        org_dir, _ = org_repo
        gitignore = org_dir / ".gitignore"
        gitignore.write_text("*.tmp\n")

        ensure_backups_ignored(org_dir / "tasks.org")
        ensure_backups_ignored(org_dir / "tasks.org")

        content = gitignore.read_text()
        assert "*.tmp" in content
        assert content.count("*.bak") == 1
