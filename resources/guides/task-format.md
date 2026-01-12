# Task Format

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

- `:CUSTOM_ID:` - Required. Use `task-<ticket-id>` format (e.g., `task-gh-123`)
- `:ID:` - Auto-generated UUID if omitted
- `:CREATED:`, `:MODIFIED:`, `:CLOSED:` - Auto-managed timestamps

## Automatic Behaviors

- `TODO→DONE`: Moves to "Completed Tasks", sets `:CLOSED:`
- `DONE→TODO`: Moves to "Tasks", clears `:CLOSED:`
- Progress cookies `[/]` update automatically
- Always search for duplicates before creating

## Link Format

`[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`
