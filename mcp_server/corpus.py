#!/usr/bin/env python
#
"""
Search across every scope at once.

Open-ended recall is inherently cross-scope. Asked to find work on a topic
from a half-remembered phrase, there is no way to know in advance whether the
answer was written up as a task, a journal entry, a project or a design note
filed a year ago -- so the search that answers it cannot be scoped to one of
them beforehand.

This unions the four corpora into a **single** ranking rather than searching
each and merging. That is the whole difference: IDF is a property of the corpus
being searched, so scoring each scope separately makes a term that is rare in
the journal and common in tasks worth different amounts in the same result set,
and the scores become incomparable exactly where they have to be compared.

The scoped tools stay, and are still the right call when the scope is known.
They carry filters this cannot -- a date window, a status, a drawer property --
and searching one scope is cheaper than searching four.
"""

# system imports
from pathlib import Path

# project imports
from mcp_server.config import global_state
from mcp_server.files import FilesCorpus, OrgRecord, org_record_to_record
from mcp_server.journal import (
    JOURNAL_FILENAME_RE,
    JournalCorpus,
    JournalEntry,
    journal_entry_to_record,
)
from mcp_server.projects import Project, ProjectCorpus, project_to_record
from mcp_server.results import DetailLevel, Record, render
from mcp_server.search import Corpus, Results, SearchDoc, search
from mcp_server.tasks import Task, TaskCorpus, task_to_record, task_warnings

# =============================================================================
# Constants
# =============================================================================

# The scopes a caller may select, in the order their results are gathered.
SCOPES: tuple[str, ...] = ("tasks", "journal", "projects", "files")

# What each scope's results are labelled with, so a caller can tell which tool
# will fetch a given hit. The scopes have different follow-up calls --
# get_task, get_journal_entry, get_project, or opening the file -- and a mixed
# result set is unusable without saying which is which.
SCOPE_LABEL: dict[str, str] = {
    "tasks": "task",
    "journal": "journal",
    "projects": "project",
    "files": "file",
}


# =============================================================================
# Scope selection
# =============================================================================


###############################################################################
#
def owned_by_typed_corpus(path: Path) -> bool:
    """
    Report whether a file is already searched by one of the typed corpora.

    Args:
        path: A candidate org file

    Returns:
        True when tasks.org, a dated journal file, or a project file.

    Note:
        Without this the same document is ranked twice and shown twice
        whenever more than one scope is selected. The predicate is applied
        whatever the scope, so the `files` scope means the same set of files
        every time rather than depending on what it was asked for alongside.

        Ownership is by the rule each typed corpus actually uses, not by
        directory, which is what keeps `tasks.org_archive` searchable: it
        sits beside tasks.org and no typed tool reads it. The same holds for a
        journal file whose name is not a date.

        `projects/index.org` is owned and therefore skipped. It is generated
        from the project files and searching it would return a table of
        contents where the project itself is the answer.
    """
    config = global_state.config

    if path == config.tasks_file:
        return True
    if path.parent == config.journal_dir:
        return bool(JOURNAL_FILENAME_RE.match(path.name))
    if path.parent == config.projects_dir:
        return path.name.endswith(".org")

    return False


###############################################################################
#
def resolve_scopes(scope: list[str] | None) -> list[str]:
    """
    Read the requested scopes, defaulting to all of them.

    Args:
        scope: Scope names, or None for every scope

    Returns:
        The scopes to search, de-duplicated and in :data:`SCOPES` order.

    Raises:
        ValueError: If a name is not a scope.
    """
    if not scope:
        return list(SCOPES)

    wanted = {name.strip().lower() for name in scope}
    if unknown := wanted - set(SCOPES):
        raise ValueError(
            f"Unknown scope: {', '.join(sorted(unknown))}. "
            f"Use one or more of: {', '.join(SCOPES)}"
        )

    return [name for name in SCOPES if name in wanted]


###############################################################################
#
def scope_documents(scope: str, headline_only: bool) -> list[SearchDoc]:
    """
    Return one scope's documents, labelled with the scope they came from.

    Args:
        scope: One of :data:`SCOPES`
        headline_only: Match headlines rather than whole records

    Returns:
        The scope's search documents. An absent scope yields none, which is
        what lets this server run somewhere with no tasks.org and no journal.
    """
    corpus: Corpus

    match scope:
        case "tasks":
            corpus = TaskCorpus(headline_only=headline_only)
        case "journal":
            corpus = JournalCorpus(headline_only=headline_only)
        case "projects":
            corpus = ProjectCorpus(headline_only=headline_only)
        case _:
            corpus = FilesCorpus(
                skip=owned_by_typed_corpus, headline_only=headline_only
            )

    return corpus.documents()


# =============================================================================
# Searching
# =============================================================================


###############################################################################
#
def search_org(
    query: str,
    scope: list[str] | None = None,
    order: str = "relevance",
    headline_only: bool = False,
) -> Results:
    """
    Search every selected scope as one corpus, ranked by relevance.

    Args:
        query: Search terms, with optional "quoted phrases"
        scope: Any combination of tasks, journal, projects and files, or None
            for all four
        order: One of the search module's orderings
        headline_only: Match against headlines rather than whole records

    Returns:
        Ranked :class:`~mcp_server.search.Results`, whose hits carry a Task,
        JournalEntry, Project or OrgRecord as their payload.

    Note:
        Relevance by default, and deliberately not recency. A cross-scope
        search is asked when the *date* is what has been forgotten; if it were
        known, the scoped tool with a date window would be the cheaper call.
    """
    docs: list[SearchDoc] = []
    for name in resolve_scopes(scope):
        docs.extend(scope_documents(name, headline_only))

    return search(docs, query, order=order)


###############################################################################
#
def payload_to_record(payload: object) -> Record:
    """
    Adapt whatever a hit carries to the shared result envelope.

    Args:
        payload: A Task, JournalEntry, Project or OrgRecord

    Returns:
        A :class:`Record` labelled with the scope it came from, so that a
        caller reading a mixed result set knows which tool fetches it.

    Raises:
        TypeError: If the payload is of no known type.

    Note:
        Each scope's own adapter renders it, rather than this deciding afresh
        what a task should look like. A task looks the same in a cross-scope
        result as in search_tasks, which is the point of there being one
        envelope.
    """
    match payload:
        case Task():
            record, scope = task_to_record(payload), "tasks"
        case JournalEntry():
            record, scope = (
                journal_entry_to_record(payload, show_date=True),
                "journal",
            )
        case Project():
            record, scope = project_to_record(payload), "projects"
        case OrgRecord():
            record, scope = org_record_to_record(payload), "files"
        case _:
            raise TypeError(f"No record adapter for {type(payload).__name__}")

    label = SCOPE_LABEL[scope]
    record.prefix = f"{label}: {record.prefix}".strip()

    return record


###############################################################################
#
def format_org_search(
    results: Results,
    detail: DetailLevel = "snippet",
    limit: int | None = None,
    offset: int = 0,
) -> str:
    """
    Format ranked cross-scope search results.

    Args:
        results: What the search returned
        detail: Envelope detail level, defaulting to snippet
        limit: Maximum matches to show; None takes the level's default
        offset: Matches to skip

    Returns:
        A rendered page whose every line names the scope it came from.

    Note:
        Carries the same report of tasks the parser cannot see that the task
        tools do. A cross-scope search is the one most likely to be trusted as
        exhaustive, so a scope that is quietly incomplete has to say so here
        above all.
    """
    records = []
    for hit in results.hits:
        record = payload_to_record(hit.doc.payload)
        record.score = hit.score
        record.matched_terms = hit.matched_terms
        record.total_terms = hit.total_terms
        records.append(record)

    warnings = task_warnings()
    if results.absent_terms:
        warnings.append(
            "Nothing in the corpus contains: "
            + ", ".join(results.absent_terms)
            + " -- these were ignored when matching."
        )

    return render(
        records,
        tool="search_org",
        header=f'search_org("{results.query.raw}")',
        detail=detail,
        limit=limit,
        offset=offset,
        query_terms=results.query.terms,
        order=results.order,
        warnings=warnings,
    )
