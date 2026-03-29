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

## Properties

- `:CUSTOM_ID:` — Required. Use `task-<ticket-id>` format (e.g., `task-gh-123`)
- `:ID:` — Auto-generated UUID if omitted
- `:CREATED:`, `:MODIFIED:`, `:CLOSED:` — Auto-managed timestamps

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

## Automatic Behaviors

- `TODO→DONE`: Moves to "Completed Tasks", sets `:CLOSED:`
- `DONE→TODO`: Moves to "Tasks", clears `:CLOSED:`
- `:MODIFIED:` updated on every change
- Progress cookies `[/]` update automatically
- High level checklist updated on create and status change

## Link Format

`[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`
