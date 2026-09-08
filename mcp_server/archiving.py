#!/usr/bin/env python
#
"""
Archiving a task out of tasks.org, by way of Emacs.

Org already knows how to archive a subtree: which file receives it, what
context to record alongside it, what level it arrives at. So Emacs does the
move -- ``org-archive-subtree`` over ``emacsclient`` -- and this module owns
everything around it: resolving what to archive, verifying what happened,
repairing the references that pointed at the task, and reporting.

**Archiving is the one write that legitimately removes a task.** That is
precisely what :func:`~mcp_server.tasks.write_tasks_org`'s guard exists to
refuse, so this cannot go through that path -- and every guarantee that path
provides has to be re-established here by hand: a recoverable pre-image, a
raw-text check that nothing else vanished, and a commit.

**No ediff.** Archiving is mechanical in the same sense as
:mod:`~mcp_server.linking` and ``reorder_task``: there is no generated prose
for anyone to review, only a subtree moving to a file org already chose.
Approval is for content a person may want to edit before it lands.

What archiving does need is *direction*, and that is a conversational
protocol rather than a parameter -- a ``confirmed`` argument the caller sets
itself proves nothing. It lives in the tool description and the task guide,
which is what an agent reads before calling.

**Emacs is the only implementation, so its absence is a hard failure.** This
is the deliberate opposite of :func:`~mcp_server.utils.request_ediff_approval`,
which shrugs and auto-approves when Emacs cannot be reached: there, falling
back means skipping a review; here there would be nothing left to do the work.
It is not gated on ``ediff_approval`` either, which configures an approval UI
rather than whether Emacs is reachable.

**Prefer a duplicate to a hole.** If verification fails, tasks.org is restored
from its pre-image and the archived copy is left where org put it. A task in
two places is recoverable by hand; a task in none is not.
"""

# system imports
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# project imports
from mcp_server.config import global_state, logger
from mcp_server.files import ARCHIVE_SUFFIX, read_org_file, walk_org_files
from mcp_server.linking import RELATED_TASKS, link_anchor_re
from mcp_server.projects import (
    get_project,
    replace_project_section,
    update_project_properties,
)
from mcp_server.tasks import (
    Task,
    extract_task_description,
    find_task,
    find_task_candidates,
    remove_high_level_task,
    scan_section_headings,
    scan_task_identities,
    write_tasks_org,
)
from mcp_server.utils import (
    backup_file,
    ensure_elisp_loaded,
    get_current_timestamp,
    get_emacsclient_path,
    quote_elisp,
    write_file,
)
from mcp_server.validation import HEADING_RE
from mcp_server.versioning import commit_file, ensure_backups_ignored

# =============================================================================
# Constants
# =============================================================================

# The elisp this server loads into Emacs to do the move.
ELISP_FILE = "emacs_archive.el"

# How long to wait for Emacs. The archive itself is immediate; the wait is for
# an Emacs busy with something else, since emacsclient queues behind whatever
# the user is doing. Seconds rather than the ediff timeout's minutes, because
# nobody is being asked to read anything.
ARCHIVE_TIMEOUT = 30

# The shape of a :CUSTOM_ID: this will hand to Emacs: letters, digits, dots,
# dashes and underscores, which is what _mint_custom_id produces. Narrower
# than org allows, for two reasons. The value is interpolated into elisp
# source, and one that cannot hold a quote, a backslash or whitespace cannot
# become code even if the quoting is wrong. It also ends up in a link anchor
# as `::#<id>`, where a colon in the id makes a link org may read differently.
CUSTOM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# The :CUSTOM_ID: line of a task, for finding one in an archive file. Anchored
# per line, so it cannot match across a heading.
CUSTOM_ID_LINE = r"^[ \t]*:CUSTOM_ID:[ \t]*{}[ \t]*$"

# Words a minted id should not end on. Taking the first few words of a headline
# regularly stops mid-phrase, and an id ending in a preposition reads as though
# it were truncated -- "...-poc-in" against a headline that continued. Only the
# trailing words are dropped: one of these in the middle is part of the phrase.
TRAILING_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "onto",
        "or",
        "over",
        "that",
        "the",
        "this",
        "to",
        "under",
        "with",
        "without",
    }
)


# =============================================================================
# Errors
# =============================================================================


###############################################################################
###############################################################################
#
class ArchiveError(ValueError):
    """
    An archive could not be completed.

    Note:
        A ValueError so that the tool dispatch reports it as the caller's
        problem to act on, which it always is: Emacs is not running, the
        buffer has unsaved changes, or the file did not end up as expected.
    """


# =============================================================================
# Results
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class ArchiveResult:
    """
    What archiving one task did, at each end.

    Attributes:
        task_id: The task's ``:CUSTOM_ID:``
        headline: The task's headline, for a report the user can read
        archive_file: The file org moved the subtree into
        custom_id_assigned: Whether the task had to be given a
            ``:CUSTOM_ID:`` before it could be archived
        project_end: What happened to the project's link -- ``repointed``,
            ``no link line``, or ``no project``
        checklist_end: What happened to the High Level Tasks item --
            ``removed`` or ``not found``
        notes: Anything true but not fatal, such as an archive location that
            searching cannot reach
    """

    task_id: str
    headline: str
    archive_file: Path
    custom_id_assigned: bool = False
    project_end: str = "no project"
    checklist_end: str = "not found"
    notes: list[str] = field(default_factory=list)


###############################################################################
###############################################################################
#
@dataclass
class ArchiveReport:
    """
    The outcome of one ``archive_tasks`` call.

    Attributes:
        archived: What was archived, in the order it was archived
        already: Tasks found already in an archive, which were left alone
        failure: Why the run stopped, or None if it did not

    Note:
        A batch stops at the first failure and reports it alongside what had
        already succeeded, rather than raising and losing that. Whatever
        stopped one task -- Emacs gone, a modified buffer, a file that did not
        verify -- is likely to stop the next one too, and a caller needs to
        know exactly how far the run got.
    """

    archived: list[ArchiveResult] = field(default_factory=list)
    already: list[tuple[str, Path]] = field(default_factory=list)
    failure: str | None = None


# =============================================================================
# Resolving What To Archive
# =============================================================================


###############################################################################
#
def resolve_targets(
    identifiers: list[str],
) -> tuple[list[Task], list[tuple[str, Path]]]:
    """
    Resolve every identifier to exactly one task, or refuse them all.

    Args:
        identifiers: Task ``:CUSTOM_ID:``s, ticket IDs, or headline
            substrings

    Returns:
        Tuple of (tasks to archive, identifiers already found in an archive).
        The tasks keep the order they were named in, with a task named twice
        listed once.

    Raises:
        ArchiveError: If any identifier matches nothing or more than one task.
            Nothing is archived in that case.

    Note:
        All-or-nothing, which is the point of the function: what the user
        confirmed was a list of tasks. Archiving the subset that happened to
        resolve is not that list, and an identifier matching two tasks is a
        question rather than a coin toss -- so every candidate is named and
        the caller can come back with a ``:CUSTOM_ID:``.

        An identifier matching nothing is checked against the archives before
        it is called a problem. That is what makes a repeated call idempotent:
        re-archiving a list that is already archived reports so and writes
        nothing, rather than refusing the whole call because the tasks are
        no longer where they were.
    """
    if not identifiers:
        raise ArchiveError("No tasks named to archive.")

    resolved: list[Task] = []
    already: list[tuple[str, Path]] = []
    problems: list[str] = []
    archives: list[tuple[Path, str]] | None = None

    for identifier in identifiers:
        candidates = find_task_candidates(identifier)

        match len(candidates):
            case 1:
                resolved.append(candidates[0])
            case 0:
                if archives is None:
                    archives = load_archives()
                if archive := find_archived(identifier, archives):
                    already.append((identifier, archive))
                else:
                    problems.append(f"  '{identifier}' matches no task")
            case _:
                named = "\n".join(
                    f"      - {task.headline}"
                    + (f" (#{task.custom_id})" if task.custom_id else "")
                    for task in candidates
                )
                problems.append(
                    f"  '{identifier}' matches {len(candidates)} tasks:"
                    f"\n{named}"
                )

    if problems:
        raise ArchiveError(
            "Nothing was archived. These identifiers do not name one task "
            "each:\n\n" + "\n".join(problems) + "\n\nName each task by its "
            ":CUSTOM_ID: -- list_tasks shows them -- and call again."
        )

    return (_unique_by_identity(resolved), already)


###############################################################################
#
def _unique_by_identity(tasks: list[Task]) -> list[Task]:
    """
    Drop tasks named more than once, keeping the first mention's order.

    Args:
        tasks: The resolved tasks

    Returns:
        The same tasks with duplicates removed.

    Note:
        A ticket ID and a ``:CUSTOM_ID:`` for the same task are two ways of
        saying one thing, and archiving it once is what was meant.
    """
    seen: set[str] = set()
    unique: list[Task] = []

    for task in tasks:
        identity = task.custom_id or f"headline:{task.headline}"
        if identity not in seen:
            seen.add(identity)
            unique.append(task)

    return unique


###############################################################################
#
def ensure_custom_id(task: Task) -> tuple[Task, bool]:
    """
    Make sure a task carries a ``:CUSTOM_ID:``, writing one if it does not.

    Args:
        task: The task about to be archived

    Returns:
        Tuple of (the task, whether an id had to be written).

    Raises:
        ArchiveError: If the task cannot be identified unambiguously in the
            raw file, so that no write can be made safely.

    Note:
        Archiving keys on ``:CUSTOM_ID:`` because Emacs has to find the
        heading and a headline is not a locator: ``find_task`` resolves a
        substring to its *first* match, which for a write that removes a task
        would archive whichever came first and report success.

        The tasks most worth archiving are the oldest ones, which are exactly
        those predating the convention, so refusing them would gut the tool.
        The id is written through the ordinary guarded path and commits on its
        own before Emacs is invoked, so a failed archive leaves a property
        addition explained by its own commit rather than a stray edit.
    """
    if task.custom_id:
        _validate_custom_id(task.custom_id)
        return (task, False)

    tasks_file = global_state.config.tasks_file
    identity = _raw_identity_for(task, tasks_file.read_text(encoding="utf-8"))
    custom_id = _mint_custom_id(task.headline)
    _validate_custom_id(custom_id)

    # find_task resolves a substring to its first match, so it is only safe to
    # locate this task by its headline once the headline is known to name one
    # task.
    if len(find_task_candidates(task.headline)) != 1:
        raise ArchiveError(
            f"The headline '{task.headline}' names more than one task, so a "
            f":CUSTOM_ID: cannot be written to the right one. Add one in "
            f"Emacs and archive by it."
        )

    _, heading, _, org = find_task(task.headline)
    heading.properties["CUSTOM_ID"] = custom_id
    heading.properties["MODIFIED"] = get_current_timestamp(active=False)

    # The task's identity in the raw file changes with this write -- it was
    # known by its headline and is now known by its id -- so the guard has to
    # be told which identity is allowed to disappear.
    write_tasks_org(
        org,
        summary=f"assign :CUSTOM_ID: {custom_id} before archiving",
        target=identity,
    )

    logger.info("Assigned :CUSTOM_ID: %s to '%s'", custom_id, task.headline)

    task, _, _, _ = find_task(custom_id)
    return (task, True)


###############################################################################
#
def _raw_identity_for(task: Task, file_content: str) -> str:
    """
    Find the identity the write guard knows a task by.

    Args:
        task: A task with no ``:CUSTOM_ID:``
        file_content: The current text of tasks.org

    Returns:
        The ``headline:<text>`` identity that
        :func:`~mcp_server.tasks.scan_task_identities` reports for this task.

    Raises:
        ArchiveError: If no identity or more than one matches the headline.

    Note:
        The scan reads the headline from the raw line, so it keeps a priority
        cookie and a progress cookie that the parsed headline does not. That
        makes the identity worth looking up rather than reconstructing: an
        exact match is used when there is one, and otherwise the headline has
        to pick out exactly one raw identity or this refuses to guess.
    """
    exact = f"headline:{task.headline}"
    identities = [
        identity
        for identity in scan_task_identities(file_content)
        if identity.startswith("headline:")
    ]

    if exact in identities:
        return exact

    containing = [
        identity for identity in identities if task.headline in identity
    ]
    if len(containing) == 1:
        return containing[0]

    raise ArchiveError(
        f"Cannot safely identify the task '{task.headline}' in tasks.org: it "
        f"has no :CUSTOM_ID: and its headline matches "
        f"{len(containing)} un-named task(s) in the file. Give it a "
        f":CUSTOM_ID: and archive it by that."
    )


###############################################################################
#
def _mint_custom_id(headline: str) -> str:
    """
    Build a ``:CUSTOM_ID:`` for a task that has none.

    Args:
        headline: The task's headline

    Returns:
        A ``task-`` prefixed slug of the headline, unique in the file.

    Note:
        Follows the guide's ``task-<identifier>`` shape, taking the leading
        words of the headline so the id says which task it names, and
        stopping short of a trailing preposition so it reads as a phrase
        rather than a truncation. A collision gets a numeric suffix rather
        than being silently reused, since two tasks sharing an id would make
        both unfindable.

        The archives are checked alongside tasks.org, because the archive is
        where this task is heading: an id already used by something archived
        would put two identically-named tasks in one file, which is the
        collision that matters here.
    """
    description = extract_task_description(headline).lower()
    words = re.findall(r"[a-z0-9]+", description)[:6]

    while len(words) > 1 and words[-1] in TRAILING_STOPWORDS:
        words.pop()

    base = "-".join(words) or "task"

    existing = set(
        scan_task_identities(
            global_state.config.tasks_file.read_text(encoding="utf-8")
        )
    )
    archives = load_archives()

    candidate = f"task-{base}"
    suffix = 2
    while candidate in existing or any(
        _matches_custom_id_line(text, candidate) for _, text in archives
    ):
        candidate = f"task-{base}-{suffix}"
        suffix += 1

    return candidate


###############################################################################
#
def _validate_custom_id(custom_id: str) -> None:
    """
    Refuse a ``:CUSTOM_ID:`` this cannot hand to Emacs safely.

    Args:
        custom_id: The id about to be interpolated into elisp

    Raises:
        ArchiveError: If the id is not the shape this server writes.
    """
    if not CUSTOM_ID_RE.match(custom_id):
        raise ArchiveError(
            f"Refusing to archive by the :CUSTOM_ID: '{custom_id}': it is not "
            f"the shape this server writes, and it has to be passed to Emacs "
            f"as elisp. Rename it to letters, digits, dots and dashes."
        )


# =============================================================================
# The Emacs Side
# =============================================================================


###############################################################################
#
def run_org_archive(tasks_file: Path, custom_id: str) -> Path:
    """
    Have Emacs archive one task, and report where it went.

    Args:
        tasks_file: The org file holding the task
        custom_id: The task's ``:CUSTOM_ID:``

    Returns:
        The file org archived the subtree into.

    Raises:
        ArchiveError: If Emacs cannot be reached, the elisp cannot be loaded,
            Emacs signals an error, or it does not answer with a usable path.

    Note:
        The seam the tests replace. Everything above and below this call is
        ordinary Python and is tested against a fake that really moves the
        heading; this function is the only part that needs a live Emacs, and
        the manual test script is what exercises it.
    """
    emacsclient = get_emacsclient_path()
    if emacsclient is None:
        raise ArchiveError(
            "Archiving needs a running Emacs: it is org's own "
            "org-archive-subtree that does the work, and emacsclient was not "
            "found. Start the Emacs server (M-x server-start), or set "
            "EMACSCLIENT_PATH, and try again. Nothing was changed."
        )

    if not ensure_elisp_loaded(ELISP_FILE):
        raise ArchiveError(
            f"Could not load {ELISP_FILE} into Emacs, so there is nothing to "
            f"do the archiving. Nothing was changed."
        )

    form = (
        f"(org-mcp-archive-subtree {quote_elisp(str(tasks_file))} "
        f"{quote_elisp(custom_id)})"
    )

    try:
        completed = subprocess.run(
            [emacsclient, "--eval", form],
            capture_output=True,
            text=True,
            timeout=ARCHIVE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        raise ArchiveError(
            f"Emacs did not answer within {ARCHIVE_TIMEOUT}s while archiving "
            f"'{custom_id}'. It may be waiting on something in the "
            f"minibuffer. Check Emacs, then check whether the task moved "
            f"before archiving it again."
        ) from error

    answer = (completed.stdout or "").strip()
    complaint = (completed.stderr or "").strip() or answer

    # An `error' in the elisp reaches us as a non-zero exit with the message
    # on stderr, so its own wording is the most useful thing to pass on.
    if completed.returncode != 0 or answer.startswith("*ERROR*"):
        raise ArchiveError(
            f"Emacs refused to archive '{custom_id}': "
            f"{complaint.removeprefix('*ERROR*:').strip()}"
        )

    return _parse_archive_path(answer, custom_id)


###############################################################################
#
def _parse_archive_path(answer: str, custom_id: str) -> Path:
    """
    Read the archive path out of what emacsclient printed.

    Args:
        answer: The stdout of the ``--eval`` call
        custom_id: The task being archived, for the error message

    Returns:
        The path Emacs reported.

    Raises:
        ArchiveError: If the answer is not a quoted absolute path.

    Note:
        ``emacsclient`` prints a returned string as an elisp string literal,
        quotes and escapes included. The answer is checked rather than
        trusted: it decides which file gets verified and committed, so an
        empty or relative path has to stop the operation rather than send the
        checks somewhere harmless.
    """
    text = answer.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")

    path = Path(text)
    if not text or not path.is_absolute():
        raise ArchiveError(
            f"Emacs did not say where '{custom_id}' was archived to (it "
            f"answered {answer!r}). The task may have moved; check tasks.org "
            f"and its archive before trying again."
        )

    return path


# =============================================================================
# Verification
# =============================================================================


###############################################################################
#
def verify_archive(
    before: str, after: str, custom_id: str, archive_file: Path
) -> list[str]:
    """
    Check that archiving one task is all that happened.

    Args:
        before: Text of tasks.org before Emacs ran
        after: Text of tasks.org after Emacs ran
        custom_id: The task that was supposed to leave
        archive_file: The file Emacs said it went into

    Returns:
        Everything wrong, as lines for a report. Empty when the archive is
        exactly what was asked for.

    Note:
        Raw text, deliberately, and for the same reason
        :func:`~mcp_server.tasks.scan_task_identities` is: asking the org
        parser whether a heading has gone missing is asking the component that
        loses headings. This is the guard that ``write_tasks_org`` would have
        applied had the write come from here, so it checks what that checks --
        no other task gone, no section gone -- plus the part only archiving
        can get wrong, which is whether the task actually arrived.
    """
    problems: list[str] = []

    before_ids = scan_task_identities(before)
    after_ids = set(scan_task_identities(after))

    vanished = [
        identity for identity in before_ids if identity not in after_ids
    ]
    collateral = [identity for identity in vanished if identity != custom_id]

    if collateral:
        lost = "\n".join(f"      - {identity}" for identity in collateral)
        problems.append(
            f"  {len(collateral)} task(s) other than '{custom_id}' left "
            f"tasks.org:\n{lost}"
        )

    if custom_id not in vanished:
        problems.append(
            f"  '{custom_id}' is still in tasks.org, so it was not archived"
        )

    after_sections = set(scan_section_headings(after))
    dropped = [
        name
        for name in scan_section_headings(before)
        if name not in after_sections
    ]
    if dropped:
        lost = "\n".join(f"      - {name}" for name in dropped)
        problems.append(f"  section heading(s) disappeared:\n{lost}")

    if not archive_file.exists():
        problems.append(f"  the archive file {archive_file} does not exist")
    elif not task_in_archive(custom_id, archive_file):
        problems.append(
            f"  '{custom_id}' is not in {archive_file}, so the task is in "
            f"neither file"
        )

    return problems


###############################################################################
#
def task_in_archive(custom_id: str, archive_file: Path) -> bool:
    """
    Report whether an archive file holds a task.

    Args:
        custom_id: The task's ``:CUSTOM_ID:``
        archive_file: The file to look in

    Returns:
        True when a ``:CUSTOM_ID:`` line in that file names this task.
    """
    text = read_org_file(archive_file)
    if text is None:
        logger.warning("Could not read the archive %s", archive_file)
        return False

    return _matches_custom_id_line(text, custom_id)


###############################################################################
#
def load_archives() -> list[tuple[Path, str]]:
    """
    Read every archive file under the search roots.

    Returns:
        Each archive file and its text.

    Note:
        Archives are recognised by org's ``<name>_archive`` convention, the
        same way :mod:`~mcp_server.files` recognises them for searching, so
        this works for whatever files an installation has rather than for one
        named file. Read once per call: an identifier that resolves to a live
        task never needs them at all, and a batch of twenty that do not should
        not walk the roots twenty times.
    """
    return [
        (path, text)
        for path in walk_org_files(global_state.config.search_roots)
        if path.name.endswith(ARCHIVE_SUFFIX)
        if (text := read_org_file(path)) is not None
    ]


###############################################################################
#
def find_archived(
    identifier: str, archives: list[tuple[Path, str]]
) -> Path | None:
    """
    Find an already-archived task by the identifier that named it.

    Args:
        identifier: What the caller called the task
        archives: The archive files and their text, from :func:`load_archives`

    Returns:
        The archive file holding it, or None.

    Note:
        A task absent from tasks.org and present in an archive has already
        been archived, which is the state the caller asked for -- so this is
        what turns a repeated call into a report instead of an error.

        Matched on ``:CUSTOM_ID:`` lines and on heading lines, never on body
        text. An archive holds the whole of the work it describes, so a
        substring of some task's notes is not evidence that this task is the
        one already there.
    """
    wanted = identifier.strip().lower()
    ids = [
        candidate
        for candidate in (identifier, f"task-{wanted}")
        if CUSTOM_ID_RE.match(candidate)
    ]

    for path, text in archives:
        if any(_matches_custom_id_line(text, custom_id) for custom_id in ids):
            return path

        if any(
            wanted in line.lower()
            for line in text.split("\n")
            if HEADING_RE.match(line)
        ):
            return path

    return None


###############################################################################
#
def _matches_custom_id_line(text: str, custom_id: str) -> bool:
    """
    Report whether a file has a ``:CUSTOM_ID:`` line naming a task.

    Args:
        text: The file's text
        custom_id: The id to look for

    Returns:
        True when a property line in that text names this task.
    """
    pattern = CUSTOM_ID_LINE.format(re.escape(custom_id))
    return re.search(pattern, text, re.MULTILINE) is not None


###############################################################################
#
def archive_notes(archive_file: Path) -> list[str]:
    """
    Report anything true about an archive location that a caller should know.

    Args:
        archive_file: The file org archived into

    Returns:
        Lines for the result, empty when the location is an ordinary one.

    Note:
        Not problems: the archive worked. But org decides the location, from
        settings this server does not own, and two of its answers change what
        happens to the task afterwards -- whether ``search_org`` can reach it
        at all, and whether its hits are marked as finished work.
    """
    notes: list[str] = []

    roots = [
        root.expanduser().resolve() for root in global_state.config.search_roots
    ]
    resolved = archive_file.resolve()

    if not any(resolved.is_relative_to(root) for root in roots):
        notes.append(
            f"{archive_file} is outside the search roots, so search_org "
            f"cannot reach the archived task. Add its directory to "
            f"SEARCH_ROOTS to keep it findable."
        )

    if not archive_file.name.endswith(ARCHIVE_SUFFIX):
        notes.append(
            f"{archive_file.name} does not end in '{ARCHIVE_SUFFIX}', so hits "
            f"from it are not marked [archived] in search results."
        )

    return notes


# =============================================================================
# The Other Ends
# =============================================================================


###############################################################################
#
def repoint_project_link(task: Task, archive_file: Path) -> str:
    """
    Point a project's link at the task's new home.

    Args:
        task: The task that was archived, with its ``:PROJECT:``
        archive_file: The file it was archived into

    Returns:
        What happened -- ``repointed``, ``no link line``, ``no project``, or
        ``project '<value>' not found``.

    Note:
        The task's ``:PROJECT:`` travels into the archive inside the drawer,
        so the project end is the half that would otherwise be left pointing
        at a heading that is no longer there. Only the file part of the link
        is rewritten: the ``::#task-id`` anchor is what
        :func:`~mcp_server.linking.link_task_to_project` judges an existing
        link by, so keeping it means linking still recognises this link and
        does not append a second one.

        A project keeps its record of work that happened rather than being
        tidied up -- archiving a task says the work is finished or abandoned,
        not that the project never had it.
    """
    if not task.project:
        return "no project"

    try:
        project = get_project(task.project)
    except ValueError:
        # A :PROJECT: naming something that no longer exists. There is no link
        # to repair, and the archive itself is already done.
        return f"project '{task.project}' not found"

    existing = project.sections.get(RELATED_TASKS, "")
    anchor = link_anchor_re(task.custom_id)

    lines = existing.split("\n")
    rewritten = [
        _rewrite_link_path(line, task.custom_id, archive_file)
        if anchor.search(line)
        else line
        for line in lines
    ]

    if rewritten == lines:
        return "no link line"

    content = replace_project_section(
        project.raw_content, RELATED_TASKS, "\n".join(rewritten)
    )
    content = update_project_properties(
        content, {"MODIFIED": get_current_timestamp(active=False)}
    )
    write_file(
        project.file_path,
        content,
        summary=(
            f"repoint {task.custom_id} at its archive in project {project.slug}"
        ),
    )

    return "repointed"


###############################################################################
#
def _rewrite_link_path(line: str, custom_id: str, archive_file: Path) -> str:
    """
    Change which file a task link points at, leaving its anchor and text.

    Args:
        line: The ``Related Tasks`` line
        custom_id: The task's ``:CUSTOM_ID:``
        archive_file: The file to point at

    Returns:
        The line, pointing at the archive.
    """
    pattern = rf"\[\[file:[^\]]*?::#{re.escape(custom_id)}\]"
    return re.sub(
        pattern, f"[[file:{tilde_path(archive_file)}::#{custom_id}]", line
    )


###############################################################################
#
def tilde_path(path: Path) -> str:
    """
    Render a path the way org links in these files are written.

    Args:
        path: An absolute path

    Returns:
        The path with the home directory as ``~``, when it is under it.

    Note:
        Org files are synced between machines whose home directories differ,
        so a link written with ``~`` keeps working and an absolute one does
        not.
    """
    home = Path.home()
    if path.is_relative_to(home):
        return f"~/{path.relative_to(home)}"
    return str(path)


###############################################################################
#
def remove_checklist_item(task: Task) -> str:
    """
    Drop the archived task's line from the High Level Tasks checklist.

    Args:
        task: The task that was archived

    Returns:
        ``removed`` or ``not found``.

    Note:
        Run only after the archive has verified, so a failed archive never
        leaves a live task with its tracking line deleted. The outcome is
        reported either way: the line is matched on the description
        :func:`~mcp_server.tasks.extract_task_description` derives from the
        headline, and a checklist worded differently from its task is a silent
        no-op otherwise.

        Written as text rather than through ``write_tasks_org``, which would
        render the file through orgmunge and drop every blank line between its
        sections. Emacs has just written this file and left its shape intact;
        deleting one checklist line must not be what reflows it.
    """
    tasks_file = global_state.config.tasks_file
    description = extract_task_description(task.headline)

    updated = remove_high_level_task(
        tasks_file.read_text(encoding="utf-8"), description
    )
    if updated is None:
        return "not found"

    write_file(
        tasks_file,
        updated,
        summary=f"drop checklist item for archived {task.custom_id}",
    )
    return "removed"


# =============================================================================
# Archiving
# =============================================================================


###############################################################################
#
def archive_task(task: Task) -> ArchiveResult:
    """
    Archive one task, verify it, and repair what pointed at it.

    Args:
        task: The task to archive, already resolved

    Returns:
        What happened, at each end.

    Raises:
        ArchiveError: If Emacs would not do it, or if the result does not
            verify -- in which case tasks.org has been restored.
    """
    task, assigned = ensure_custom_id(task)
    tasks_file = global_state.config.tasks_file

    before = tasks_file.read_text(encoding="utf-8")

    # Taken before Emacs is invoked, and kept until the result verifies. This
    # is a distinct artifact from write_file's `.bak`, which holds whatever the
    # last write replaced, so neither clobbers the other.
    ensure_backups_ignored(tasks_file)
    pre_image = backup_file(tasks_file)

    try:
        archive_file = run_org_archive(tasks_file, task.custom_id)
    except ArchiveError:
        # Emacs refused, so tasks.org is untouched and the pre-image is just
        # litter. Every error the elisp raises happens either before the
        # subtree moves or before the buffer is saved, so what is on disk is
        # what the pre-image holds.
        pre_image.unlink(missing_ok=True)
        raise

    after = tasks_file.read_text(encoding="utf-8")

    if problems := verify_archive(before, after, task.custom_id, archive_file):
        _restore(tasks_file, pre_image, task.custom_id)
        raise ArchiveError(
            f"Archiving '{task.custom_id}' did not leave tasks.org as it "
            f"should have:\n\n" + "\n".join(problems) + "\n\n"
            f"tasks.org has been restored from {pre_image}, and the copy org "
            f"wrote into {archive_file} has been left alone -- the task is "
            f"now in both places rather than at risk in neither. Revert the "
            f"{tasks_file.name} buffer in Emacs before editing it, then "
            f"reconcile the two by hand."
        )

    pre_image.unlink(missing_ok=True)

    # Emacs wrote both files, so neither went through write_file and neither
    # has been committed. Two commits rather than one: the archive may live in
    # a different repository from tasks.org, or in none.
    commit_file(tasks_file, f"archive task {task.custom_id}")
    commit_file(archive_file, f"archive task {task.custom_id}")

    # Past this point the task is archived, so nothing below may turn that
    # into a failure. The two repairs are reported, and a repair that cannot
    # be made is reported as such rather than raised: what a caller must never
    # be told is that an archive failed when the task has in fact moved.
    return ArchiveResult(
        task_id=task.custom_id,
        headline=task.headline,
        archive_file=archive_file,
        custom_id_assigned=assigned,
        project_end=_repair(
            "project", lambda: repoint_project_link(task, archive_file)
        ),
        checklist_end=_repair("checklist", lambda: remove_checklist_item(task)),
        notes=archive_notes(archive_file),
    )


###############################################################################
#
def _repair(end: str, repair: Callable[[], str]) -> str:
    """
    Run one post-archive repair, reporting a failure instead of raising it.

    Args:
        end: Which end is being repaired, for the log and the report
        repair: The repair to attempt, returning what it did

    Returns:
        What the repair did, or why it could not be done.

    Note:
        Follows the rule :func:`~mcp_server.linking._refresh_index` follows: a
        secondary write must not make a completed operation report as broken.
        The difference from that one is that this is reported to the caller as
        well as logged, because a project still pointing into tasks.org is
        something a person has to finish by hand.
    """
    try:
        return repair()
    except (ValueError, OSError) as error:
        logger.warning("Could not repair the %s end: %r", end, error)
        return f"NOT repaired: {error}"


###############################################################################
#
def _restore(tasks_file: Path, pre_image: Path, custom_id: str) -> None:
    """
    Put tasks.org back to what it was before Emacs touched it.

    Args:
        tasks_file: The file to restore
        pre_image: The copy taken before archiving
        custom_id: The task that was being archived, for the commit message

    Note:
        Through :func:`~mcp_server.utils.write_file` rather than a plain copy,
        so the rollback is committed like any other write. Otherwise git would
        record the archive and not its undo, and the next ordinary write would
        overwrite the only remaining copy of what Emacs produced.
    """
    try:
        write_file(
            tasks_file,
            pre_image.read_text(encoding="utf-8"),
            summary=f"restore tasks.org after failed archive of {custom_id}",
        )
    except OSError as error:
        logger.error("Could not restore %s: %r", tasks_file, error)


###############################################################################
#
def archive_tasks(identifiers: list[str]) -> ArchiveReport:
    """
    Archive the named tasks out of tasks.org.

    Args:
        identifiers: Task ``:CUSTOM_ID:``s, ticket IDs, or headline
            substrings. Every one must name exactly one task.

    Returns:
        What was archived, what was already archived, and what stopped the run
        if anything did.

    Raises:
        ArchiveError: If the identifiers do not resolve one-to-one, in which
            case nothing at all was archived.

    Note:
        Resolution is all-or-nothing and happens first; the archiving itself
        goes one task at a time, verified after each, and stops at the first
        failure. Carrying on past one would repeat whatever went wrong for
        every remaining task.
    """
    targets, already = resolve_targets(identifiers)
    report = ArchiveReport(already=already)

    for task in targets:
        try:
            report.archived.append(archive_task(task))
        except ArchiveError as error:
            report.failure = str(error)
            break

    return report


# =============================================================================
# Formatting
# =============================================================================


###############################################################################
#
def format_archive_report(report: ArchiveReport) -> str:
    """
    Render an archive report for a caller.

    Args:
        report: What the run did

    Returns:
        A line per task naming where it went and what happened at each end,
        with anything that stopped the run last.

    Note:
        A partial run reports what succeeded before what failed, so that a
        caller reading the failure can tell which tasks it still applies to.
    """
    lines: list[str] = []

    for result in report.archived:
        lines.append(f"✓ Archived {result.task_id} -- {result.headline}")
        lines.append(f"    to:          {result.archive_file}")
        if result.custom_id_assigned:
            lines.append(
                f"    :CUSTOM_ID:  assigned as {result.task_id} before "
                f"archiving"
            )
        lines.append(f"    project:     {result.project_end}")
        lines.append(f"    checklist:   {result.checklist_end}")
        for note in result.notes:
            lines.append(f"    note:        {note}")

    for custom_id, archive in report.already:
        lines.append(f"= {custom_id} was already archived in {archive}")

    if report.failure:
        if lines:
            lines.append("")
        lines.append(f"✗ Stopped: {report.failure}")

    if not lines:
        lines.append("Nothing to archive.")

    return "\n".join(lines)
