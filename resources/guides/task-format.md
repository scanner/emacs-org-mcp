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
- `:PROJECT:` — Required when the task belongs to a project. Value is the
  project's `:CUSTOM_ID:` (e.g., `project-booklore`). See "Linking Tasks to
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

**Required step when creating or updating a task.** Linking is two-sided and
the two sides are separate calls:

1. `list_projects` (or `search_projects`) to find a matching project.
2. If one matches, set `:PROJECT: project-<slug>` in the task's PROPERTIES
   drawer — this is the task → project half.
3. Call `link_task_to_project` to add the link to the project's
   `Related Tasks` section — this is the project → task half.

`link_task_to_project` only writes the project file. It does **not** set
`:PROJECT:` on the task; do that yourself in the same `task_entry`.

```org
** TODO GH-28 Implement chunking
:PROPERTIES:
   :CUSTOM_ID: task-gh-28
   :PROJECT:  project-booklore
:END:
```

```json
{"project_identifier": "booklore",
 "task_link": "- [[file:~/org/tasks.org::#task-gh-28][GH-28 Implement chunking]]"}
```

If no project matches, skip both steps — do not invent a project.

## Automatic Behaviors

- `TODO→DONE`: Moves to "Completed Tasks", sets `:CLOSED:`
- `DONE→TODO`: Moves to "Tasks", clears `:CLOSED:`
- `:MODIFIED:` updated on every change
- Progress cookies `[/]` update automatically
- High level checklist updated on create and status change

## Link Format

`[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`
