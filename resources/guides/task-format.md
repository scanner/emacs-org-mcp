# Task Format

## Sections

Tasks live in `tasks.org` under two top-level headings:

- **Tasks** — active/TODO tasks
- **Completed Tasks** — finished/DONE tasks

There is also a **High Level Tasks (in order)** checklist that is automatically
maintained when tasks are created or completed.

## Structure

```org
** TODO GH-123 Task description
:PROPERTIES:
   :CUSTOM_ID: task-gh-123
:END:

*** Description
Task purpose and context.

*** Related Issues
- [[https://github.com/org/repo/issues/123][GH-123 - Issue title]]

*** Related PRs
- [[https://github.com/org/repo/pull/456][#456 - PR description]]

*** Task items [/]
- [ ] First item
- [X] Completed item

*** Notes
Additional information.
```

## Heading Levels

**A task is one `**` heading. Every subsection must be `***` or deeper.**

```org
** TODO GH-123 Task description   <- the task
*** Description                   <- correct
**** Background                   <- correct
** Notes                          <- WRONG: starts a second task
```

A stray `**` splits the entry and drops everything after it. The server
rejects such entries and names the bad line.

Org reads a leading `*` as a heading **even inside `#+begin_src`**. Quote org
syntax inside a block and the server comma-escapes it for you:

```org
#+begin_example
,* Tasks
#+end_example
```

## Properties

- `:CUSTOM_ID:` — Required. Use `task-<ticket-id>` format (e.g., `task-gh-123`)
- `:ID:` — Auto-generated UUID if omitted
- `:CREATED:`, `:MODIFIED:`, `:CLOSED:` — Auto-managed timestamps
- `:PROJECT:` — The project's `:CUSTOM_ID:` (e.g., `project-booklore`).
  Written by `link_task_to_project`, not by hand. See "Linking Tasks to
  Projects" below.

## Finding Tasks

The `get_task` tool accepts any of these as an identifier:

- **CUSTOM_ID:** `task-gh-123`
- **Ticket ID:** `GH-123`
- **Headline substring:** `authentication bug`

The same identifiers work for `update_task` and `move_task`.

## Creating Tasks

The `create_task` tool takes a `section` and a `task_entry` string — the
complete org-formatted entry including the heading, PROPERTIES drawer, and all
subsections. Always `search_tasks` first to avoid duplicates.

## Updating Tasks

The `update_task` tool takes an `identifier` (to find the task) and a
`task_entry` string (the complete replacement). Preserve all existing PROPERTIES
(`:ID:`, `:CUSTOM_ID:`, `:CREATED:`) when updating.

## Linking Tasks to Projects

**Required step when creating or updating a task.** Linking is one call:

1. `list_projects` (or `search_projects`) to find a matching project.
2. If one matches, call `link_task_to_project` with the task and the project.

That maintains both ends — the task's `:PROJECT:` property and the project's
`Related Tasks` section. Do **not** set `:PROJECT:` by hand in `task_entry`:
the tool owns that field, which is what keeps its value in one shape.

```json
{"task_identifier": "task-gh-28", "project_identifier": "booklore"}
```

The result reports what happened at each end:

```
✓ Linked task-gh-28 and booklore
    task end:    task :PROJECT: set
    project end: added to the project's Related Tasks
```

It is idempotent, so it is safe to call again — linking something already
linked writes nothing. Use `unlink_task_from_project` to undo it, which also
clears both ends.

Neither asks for approval. A link is mechanical: once you have decided the two
are related there is nothing to review.

A task may belong to one project. Linking a task that is already linked
elsewhere is refused — unlink it first, so the other project's `Related Tasks`
does not keep pointing at it.

If no project matches, do not link — and do not invent a project.

## Archiving Tasks

`archive_tasks` moves tasks out of `tasks.org` by calling org's own
`org-archive-subtree` in Emacs. The subtree lands in the archive file org is
configured to use — `tasks.org_archive` by default — keeping its properties,
including `:CUSTOM_ID:` and `:PROJECT:`.

Archive work that is finished and recorded, or abandoned. A `tasks.org` that
only ever grows makes every listing and search cost more, and old tasks crowd
out the ones that matter.

### Only archive what the user asked for

Archiving is not reversible by any tool here, so the direction has to come
from the user. Three cases:

1. **The user named tasks** — "archive task-gh-28", "archive these three".
   Archive them.
2. **The user described a class of tasks** — "everything about the old
   importer", "anything untouched since the spring". Find the candidates,
   present them as a list of headlines, and **ask before calling**. Your
   reading of the class may not be theirs, and the confirmation is where that
   gets caught.
3. **You think tasks look stale** — say which and why, and wait to be told.
   Never archive on your own initiative. The signal is on every `list_tasks`
   line already: position in the section, plus the `:MODIFIED:` age. Ask when
   the active section has grown enough that reading it costs more than it
   returns; `org_stats` is the cheap way to see that.

### What the call does

```json
{"identifiers": ["task-gh-28", "GH-31", "the old importer rewrite"]}
```

Every identifier must name **exactly one** task. One that matches nothing, or
matches two, refuses the whole call and names the candidates — so a confirmed
list is never partly archived. Prefer `:CUSTOM_ID:`, which `list_tasks` shows
on every line.

The result names both ends for each task:

```
✓ Archived task-gh-28 -- GH-28 Add multi-provider support
    to:          ~/org/tasks.org_archive
    project:     repointed
    checklist:   removed
```

- **project** — a linked project's `Related Tasks` line is rewritten to point
  into the archive file, so the project keeps its record of the work.
- **checklist** — the task's `High Level Tasks` line is removed. `not found`
  means the checklist wording differs from the headline; remove it by hand if
  it should go.

Other behaviours worth knowing:

- **No approval dialog.** The move is mechanical, like linking.
- **A task with no `:CUSTOM_ID:` is given one first**, because Emacs is never
  handed a headline to match on. It appears as its own commit.
- **Idempotent.** Archiving something already archived reports that and
  writes nothing, so a list that partly succeeded can just be run again.
- **Emacs is required.** There is no fallback: org does the archiving. If
  `emacsclient` cannot be reached, or the `tasks.org` buffer has unsaved
  changes, the call fails and nothing moves.
- **Batches stop at the first failure**, reporting what was archived before
  it.

### Finding archived work again

There is no `unarchive` tool, and the typed task tools do not see archive
files. `search_org` does — hits from an archive are marked `[archived]`,
meaning the work is finished or abandoned:

```json
{"query": "old importer rewrite", "scope": "files"}
```

## Automatic Behaviors

- `TODO→DONE`: Moves to "Completed Tasks", sets `:CLOSED:`
- `DONE→TODO`: Moves to "Tasks", clears `:CLOSED:`
- `:MODIFIED:` updated on every change
- Progress cookies `[/]` are recounted by Emacs when you edit the list in
  org-mode; the server preserves whatever the cookie says
- High level checklist updated on create, status change, and archive

## Link Format

`[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`
