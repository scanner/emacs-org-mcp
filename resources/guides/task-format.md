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

## Automatic Behaviors

- `TODO→DONE`: Moves to "Completed Tasks", sets `:CLOSED:`
- `DONE→TODO`: Moves to "Tasks", clears `:CLOSED:`
- `:MODIFIED:` updated on every change
- Progress cookies `[/]` update automatically
- High level checklist updated on create and status change

## Link Format

`[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`
