# Task Format Guide for emacs-org MCP

## Overview

Tasks are stored in `~/org/tasks.org` (or the configured org directory) in org-mode format. The file has multiple sections for organizing tasks, with automatic management of a high-level checklist.

## File Structure

```org
* High Level Tasks (in order) [1/2]
- [X] Completed task description
- [ ] Active task description

* Tasks

** TODO Task heading
:PROPERTIES:
   :ID:       UUID-HERE
   :CUSTOM_ID: task-identifier
   :CREATED:  <YYYY-MM-DD Day HH:MM>
   :MODIFIED: [YYYY-MM-DD Day HH:MM]
:END:

*** Description
Task description and purpose

*** Task items [1/3]
- [X] Completed item
- [ ] Pending item
- [ ] Another item

* Completed Tasks

** DONE Previous task
:PROPERTIES:
   :ID:       UUID-HERE
   :CUSTOM_ID: task-identifier
   :CREATED:  <YYYY-MM-DD Day HH:MM>
   :MODIFIED: [YYYY-MM-DD Day HH:MM]
   :CLOSED:   <YYYY-MM-DD Day HH:MM>
:END:
```

## Task Heading Format

**Format:** `** TODO/DONE [TICKET-ID] Task description`

- Status: `TODO` (active) or `DONE` (completed)
- Optional ticket ID: `GH-123` for GitHub issues, etc.
- Description: Clear, concise task summary

## Properties Drawer

**Required Properties:**
- `:ID:` - UUID for org-mode compatibility (auto-generated if not provided)
- `:CUSTOM_ID:` - Stable identifier for linking (e.g., `task-gh-123`)

**Automatic Timestamp Properties:**
- `:CREATED:` - Active timestamp `<>` set when task is created
- `:MODIFIED:` - Inactive timestamp `[]` updated on every modification
- `:CLOSED:` - Active timestamp `<>` set when marked DONE (cleared when reopened)

**Note:** All timestamps are naive (no timezone) as org-mode doesn't support timezone information.

## Task Subsections

Use `***` level headings for subsections:

- `*** Description` - Task purpose and context
- `*** Related Issues` - GitHub issue links if multiple issues
- `*** Related PRs` - Pull request links
- `*** Task items [/]` - Checkbox list with progress tracking
- `*** Notes` - Additional information, code blocks, etc.

## Progress Tracking

**Checkbox format:** `- [ ]` (incomplete) or `- [X]` (complete)
**Progress cookie:** `[1/3]` auto-updates as items are checked

Example:
```org
*** Task items [2/3]
- [X] First item
- [X] Second item
- [ ] Third item
```

## Linking to Tasks

**From journal entries:** Use org-mode links to reference tasks:
```org
** 14:30 Work on authentication feature
- Made progress on [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2 task]]
- Completed first two subtasks
```

**Link format:** `[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`

This creates a clickable link that jumps directly to the task.

## Automatic Behaviors

1. **Section Movement:** Changing status from `TODO` to `DONE` automatically moves the task to "Completed Tasks" section
2. **High-Level Checklist:** The MCP server maintains a checklist overview at the top of the file
3. **Timestamp Management:** CREATED, MODIFIED, and CLOSED timestamps are managed automatically
4. **Progress Cookies:** `[/]` patterns auto-update based on checkbox states
5. **UUID Generation:** If `:ID:` is not provided, the MCP server generates one automatically

## When Creating Tasks

1. **Check for duplicates:** Always search before creating new tasks
2. **Use complete org format:** Provide the full task entry as an org-formatted string
3. **Include PROPERTIES drawer:** With `:CUSTOM_ID:` (`:ID:` is auto-generated if omitted)
4. **Structure subsections:** Use `***` level headings appropriately
5. **Use progress cookies:** Add `[/]` after section headings with checkboxes

## When Updating Tasks

1. **Preserve structure:** Keep all subsections and properties
2. **Update MODIFIED timestamp:** This happens automatically
3. **Status changes:** Changing TODO↔DONE triggers automatic section movement
4. **Edit liberally:** The task content can be edited before approval (if ediff enabled)
