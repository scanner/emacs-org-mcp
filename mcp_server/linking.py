#!/usr/bin/env python
#
"""
Linking a task to a project, and unlinking it again.

A link is mechanical. Once someone has decided that a task belongs to a
project, the link itself carries no judgement: it is one known-shaped line in a
known section, and one property in a drawer. There is nothing to review, so
there is no ediff approval here -- approval earns its place when generated
prose is being written into a file, because that is when a person may want to
edit it before it lands. A link is not prose.

**Both ends, or the link is half made.** The task carries ``:PROJECT:`` and the
project lists the task under ``Related Tasks``. Leaving either to the caller is
how the two drift apart, which is visible in the live data: 9 tasks hold a
``:PROJECT:`` the guides do not sanction, because nothing ever wrote it in one
place.

**Not atomic, and that is fine.** These are two files, so a failure between the
two writes leaves one end done. Both ends are validated and both contents
computed before anything is written, which makes that window small -- but the
real answer is that the operation is idempotent, so re-running it completes
whichever end is missing. That is a better guarantee than a claim of atomicity
this cannot deliver.

**Idempotency is judged on the link, not on the text.** The project end matches
the ``#task-id`` anchor rather than the rendered line, because a task's
headline changes over its life and a line-text comparison would append a second
link after any rename. The task end accepts any ``:PROJECT:`` value that
resolves to the same project and rewrites it to canonical form, so an
unsanctioned value is repaired by the next ordinary link rather than needing a
migration.
"""

# system imports
import re
from dataclasses import dataclass

# project imports
from mcp_server.config import logger
from mcp_server.projects import (
    Project,
    get_project,
    regenerate_project_index,
    replace_project_section,
    update_project_properties,
)
from mcp_server.tasks import Task, find_task, write_tasks_org
from mcp_server.utils import get_current_timestamp, write_file

# =============================================================================
# Constants
# =============================================================================

# The section of a project file that lists its tasks.
RELATED_TASKS = "Related Tasks"


# =============================================================================
# Link shape
# =============================================================================


###############################################################################
#
def task_link_line(task: Task) -> str:
    """
    Render the ``Related Tasks`` line for a task.

    Args:
        task: The task to link to

    Returns:
        An org list item linking to the task by its ``:CUSTOM_ID:`` anchor.
    """
    return f"- [[file:~/org/tasks.org::#{task.custom_id}][{task.headline}]]"


###############################################################################
#
def link_anchor_re(custom_id: str) -> re.Pattern[str]:
    """
    Build a pattern matching a link to one task.

    Args:
        custom_id: The task's ``:CUSTOM_ID:``

    Returns:
        A pattern matching that task's link anchor and nothing else.

    Note:
        Anchored on the closing bracket so that ``#task-rb-1`` does not also
        match ``#task-rb-10``, and matching the anchor rather than the whole
        line so that renaming a task does not hide its existing link.
    """
    return re.compile(rf"::#{re.escape(custom_id)}\]")


# =============================================================================
# Results
# =============================================================================


###############################################################################
###############################################################################
#
@dataclass
class LinkResult:
    """
    What a link or unlink actually did, at each end.

    Attributes:
        task_id: The task's ``:CUSTOM_ID:``
        project_slug: The project's slug
        task_end: What happened to the task's ``:PROJECT:`` property --
            ``set``, ``normalized``, ``cleared``, or ``unchanged``
        project_end: What happened in the project's Related Tasks section --
            ``added``, ``removed``, or ``unchanged``
    """

    task_id: str
    project_slug: str
    task_end: str
    project_end: str

    ###########################################################################
    #
    @property
    def changed(self) -> bool:
        """Report whether either end was written."""
        return self.task_end != "unchanged" or self.project_end != "unchanged"


###############################################################################
#
def format_link_result(result: LinkResult, verb: str) -> str:
    """
    Render a link or unlink result for a caller.

    Args:
        result: What happened
        verb: ``Linked`` or ``Unlinked``

    Returns:
        A short report naming both ends, so a partially-complete link is
        visible rather than being reported as a plain success.
    """
    ends = {
        "set": "task :PROJECT: set",
        "normalized": "task :PROJECT: rewritten to canonical form",
        "cleared": "task :PROJECT: cleared",
        "added": "added to the project's Related Tasks",
        "removed": "removed from the project's Related Tasks",
        "unchanged": "already correct",
    }

    headline = (
        f"✓ {verb} {result.task_id} and {result.project_slug}"
        if result.changed
        else f"= {result.task_id} and {result.project_slug} already as asked"
    )

    return "\n".join(
        [
            headline,
            f"    task end:    {ends[result.task_end]}",
            f"    project end: {ends[result.project_end]}",
        ]
    )


# =============================================================================
# Linking
# =============================================================================


###############################################################################
#
def _set_task_project(
    task_identifier: str, project: Project | None
) -> tuple[Task, str]:
    """
    Point a task's ``:PROJECT:`` at a project, or clear it.

    Args:
        task_identifier: How to find the task
        project: The project to point at, or None to clear

    Returns:
        Tuple of (the task, what happened) where the second is ``set``,
        ``normalized``, ``cleared`` or ``unchanged``.

    Raises:
        ValueError: If the task has no ``:CUSTOM_ID:`` to link by, or is
            already linked to a different project.
    """
    task, heading, _, org = find_task(task_identifier)

    if not task.custom_id:
        raise ValueError(
            f"Task '{task.headline}' has no :CUSTOM_ID:, so there is nothing "
            f"for a project to link to. Give it one first."
        )

    current = task.project.strip()
    canonical = project.custom_id if project else ""

    if project is None:
        outcome = "cleared" if current else "unchanged"
        if current:
            heading.properties.pop("PROJECT", None)
    elif current == canonical:
        outcome = "unchanged"
    elif current and _resolves_to(current, project):
        # A value naming this same project in some other form. Rewriting it is
        # what repairs an unsanctioned value during ordinary use.
        heading.properties["PROJECT"] = canonical
        outcome = "normalized"
    elif current:
        raise ValueError(
            f"Task '{task.custom_id}' is already linked to '{current}'. "
            f"Unlink it from that project before linking it to "
            f"'{canonical}', so the other project's Related Tasks does not "
            f"keep pointing at it."
        )
    else:
        heading.properties["PROJECT"] = canonical
        outcome = "set"

    if outcome != "unchanged":
        heading.properties["MODIFIED"] = get_current_timestamp(active=False)
        write_tasks_org(
            org,
            summary=f"link {task.custom_id} to {canonical or 'no project'}",
            target=task.custom_id,
        )

    return (task, outcome)


###############################################################################
#
def _resolves_to(value: str, project: Project) -> bool:
    """
    Report whether a ``:PROJECT:`` value names this project.

    Args:
        value: An existing ``:PROJECT:`` value
        project: The project being linked

    Returns:
        True when the value identifies this project, in any accepted form.
    """
    try:
        return get_project(value).slug == project.slug
    except ValueError:
        return False


###############################################################################
#
def _write_related_tasks(project: Project, section: str, summary: str) -> None:
    """
    Replace a project's Related Tasks section and write the file.

    Args:
        project: The project to write
        section: The new section content
        summary: Git commit summary
    """
    content = replace_project_section(
        project.raw_content, RELATED_TASKS, section
    )
    content = update_project_properties(
        content, {"MODIFIED": get_current_timestamp(active=False)}
    )
    write_file(project.file_path, content, summary=summary)


###############################################################################
#
def link_task_to_project(
    task_identifier: str, project_identifier: str
) -> LinkResult:
    """
    Link a task and a project, at both ends.

    Args:
        task_identifier: Task ``:CUSTOM_ID:``, ticket ID, or headline substring
        project_identifier: Project slug, ``:CUSTOM_ID:``, or title substring

    Returns:
        What happened at each end.

    Raises:
        ValueError: If either does not exist, if the task has no
            ``:CUSTOM_ID:``, or if it is already linked to another project.

    Note:
        Idempotent. Linking something already linked reports that and writes
        nothing, so a retry after a partial failure completes the missing end
        rather than duplicating the finished one.
    """
    project = get_project(project_identifier)
    task, task_end = _set_task_project(task_identifier, project)

    existing = project.sections.get(RELATED_TASKS, "")
    anchor = link_anchor_re(task.custom_id)
    lines = [line for line in existing.split("\n") if line.strip()]

    if any(anchor.search(line) for line in lines):
        project_end = "unchanged"
    else:
        lines.append(task_link_line(task))
        _write_related_tasks(
            project,
            "\n".join(lines),
            summary=f"link task {task.custom_id} to project {project.slug}",
        )
        project_end = "added"

    _refresh_index()

    return LinkResult(
        task_id=task.custom_id,
        project_slug=project.slug,
        task_end=task_end,
        project_end=project_end,
    )


###############################################################################
#
def unlink_task_from_project(
    task_identifier: str, project_identifier: str
) -> LinkResult:
    """
    Remove the link between a task and a project, at both ends.

    Args:
        task_identifier: Task ``:CUSTOM_ID:``, ticket ID, or headline substring
        project_identifier: Project slug, ``:CUSTOM_ID:``, or title substring

    Returns:
        What happened at each end.

    Raises:
        ValueError: If either does not exist.

    Note:
        Also idempotent: unlinking something not linked reports that and
        writes nothing. A link that cannot be undone without hand-editing is
        only half a feature, which is why this exists alongside the link.
    """
    project = get_project(project_identifier)
    task, _, _, _ = find_task(task_identifier)

    existing = project.sections.get(RELATED_TASKS, "")
    anchor = link_anchor_re(task.custom_id)
    kept = [
        line
        for line in existing.split("\n")
        if line.strip() and not anchor.search(line)
    ]

    if len(kept) == len([ln for ln in existing.split("\n") if ln.strip()]):
        project_end = "unchanged"
    else:
        _write_related_tasks(
            project,
            "\n".join(kept),
            summary=(
                f"unlink task {task.custom_id} from project {project.slug}"
            ),
        )
        project_end = "removed"

    # Only clear :PROJECT: if it actually points at this project. A task whose
    # property names something else is not this link's business.
    task_end = "unchanged"
    if task.project and _resolves_to(task.project, project):
        _, task_end = _set_task_project(task_identifier, None)

    _refresh_index()

    return LinkResult(
        task_id=task.custom_id or task.headline,
        project_slug=project.slug,
        task_end=task_end,
        project_end=project_end,
    )


###############################################################################
#
def _refresh_index() -> None:
    """
    Rebuild the project index, without letting it fail a link.

    Note:
        The index is a derived artifact rebuilt from a directory scan, not part
        of the link. A healthy link must not report as broken because the
        index could not be regenerated, so this follows versioning.py's rule:
        log it and carry on.
    """
    try:
        regenerate_project_index()
    except Exception as error:  # noqa: BLE001 - a derived file, never fatal
        logger.warning("Could not regenerate the project index: %s", error)
