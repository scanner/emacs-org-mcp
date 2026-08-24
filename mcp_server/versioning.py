"""
Git versioning for org files the server modifies.

Every write the server makes is committed to the org file's own git repository,
so the file's history becomes a record of what changed and when.  This is what
turns a bad write from an incident into a ``git revert``: the 2026-08-23 data
loss was recoverable only because an Emacs autosave happened to exist.

Design rules, in order of importance:

1. **Versioning never breaks an org operation.**  By the time we are called the
   file is already written.  Not a repo, no git binary, a held ``index.lock``,
   a rebase in progress -- all of these are logged and shrugged off.
2. **Only the file we touched is committed.**  Commits use a pathspec, so
   anything else the user has staged is left exactly as it was.
3. **We never create a repository.**  If the org directory is not already
   version controlled, this module does nothing at all.

Because a pathspec commit takes the file's current working-tree content, edits
made outside the server since the last commit are swept into the next one.
That is intentional: no version of the file goes unrecorded, even when the
server was not the one that changed it.

IMPORTANT: this uses ``repo.git.commit(...)`` rather than
``repo.index.commit(...)``.  The latter commits the *entire* index, which would
quietly capture unrelated work the user had staged.  Only a pathspec commit has
the containment property rule 2 requires.
"""

# system imports
from pathlib import Path

# 3rd party imports
from git import Repo
from git.exc import GitError, InvalidGitRepositoryError, NoSuchPathError

# project imports
from mcp_server.config import global_state, logger

# =============================================================================
# Constants
# =============================================================================

# Marker files that mean a multi-step git operation is underway.  Committing
# into one of these would entangle our write with the user's operation.  All of
# these live in the per-worktree git dir, not the common dir.
IN_PROGRESS_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "rebase-merge",
    "rebase-apply",
)


# =============================================================================
# Repository Discovery
# =============================================================================


###############################################################################
#
def get_repo(path: Path) -> Repo | None:
    """
    Find the git repository containing a file.

    Args:
        path: Path to a file, which need not exist yet

    Returns:
        The :class:`git.Repo` containing it, or None if it is not inside a git
        repository.

    Note:
        Discovery searches upward from the file's directory, so a symlinked org
        directory or a worktree both resolve correctly.  ``~/org`` being a
        symlink into a synced folder is the normal case here.
    """
    parent = path.parent
    if not parent.is_dir():
        return None

    try:
        return Repo(parent, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError):
        logger.debug("Not versioning %s: not in a git repository", path)
        return None
    except GitError as e:
        logger.warning("Could not open a repository for %s: %r", path, e)
        return None


###############################################################################
#
def operation_in_progress(repo: Repo) -> str | None:
    """
    Report whether a multi-step git operation is underway.

    Args:
        repo: The repository to inspect

    Returns:
        The name of the in-progress operation, or None if the repo is idle.
    """
    git_dir = Path(repo.git_dir)
    return next(
        (
            marker
            for marker in IN_PROGRESS_MARKERS
            if (git_dir / marker).exists()
        ),
        None,
    )


# =============================================================================
# Commit
# =============================================================================


###############################################################################
#
def commit_file(path: Path, summary: str) -> bool:
    """
    Commit a single org file to its repository, best effort.

    Args:
        path: The org file that was just written
        summary: Short description of the change, e.g. "update task task-gh-28"

    Returns:
        True if a commit was created; False for every other outcome --
        versioning disabled, not a repository, nothing changed, or git failed.

    Note:
        This never raises.  The file on disk is already correct; failing to
        record it in git is worth a log line, not a failed tool call.
    """
    if not global_state.config.git_autocommit:
        return False

    repo = get_repo(path)
    if repo is None:
        return False

    try:
        if busy := operation_in_progress(repo):
            logger.warning(
                "Not committing %s: git %s in progress in %s",
                path,
                busy,
                repo.working_tree_dir,
            )
            return False

        target = str(path)

        # Stage the file.  Needed for paths git has not seen before, since a
        # pathspec commit will not match an untracked file.
        repo.git.add("--", target)

        # Nothing to do if the content already matches HEAD.
        if not repo.git.diff("--cached", "--name-only", "--", target).strip():
            logger.debug("Not committing %s: no change", path)
            return False

        # Pathspec commit: takes this file's working-tree content and leaves
        # the rest of the index alone, so anything else the user has staged is
        # untouched. Hooks are skipped -- an org write must not be blocked by
        # someone's pre-commit linter.
        repo.git.commit(
            "--no-verify", "-m", f"emacs-org-mcp: {summary}", "--", target
        )
    except GitError as e:
        logger.warning("Could not commit %s: %r", path, e)
        return False
    except OSError as e:
        logger.warning("Could not commit %s: %r", path, e)
        return False

    logger.info("Committed %s: %s", path, summary)
    return True


###############################################################################
#
def ensure_backups_ignored(path: Path) -> None:
    """
    Make sure the repository ignores the ``.bak`` files we write.

    Args:
        path: An org file inside the repository to update

    Note:
        Backups sit next to the file they protect, which in a synced org
        directory means they would otherwise be committed and replicated to
        every machine.  The rule is appended once; an existing ``.gitignore``
        is never rewritten.
    """
    if not global_state.config.git_autocommit:
        return

    repo = get_repo(path)
    if repo is None or repo.working_tree_dir is None:
        return

    gitignore = Path(repo.working_tree_dir) / ".gitignore"
    try:
        existing = (
            gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        )
        if any(line.strip() == "*.bak" for line in existing.split("\n")):
            return

        prefix = "" if not existing or existing.endswith("\n") else "\n"
        gitignore.write_text(
            f"{existing}{prefix}# Backups written by emacs-org-mcp\n*.bak\n",
            encoding="utf-8",
        )
        logger.info("Added *.bak to %s", gitignore)
    except OSError as e:
        logger.warning("Could not update %s: %r", gitignore, e)
