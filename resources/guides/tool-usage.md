# Tool Usage Guide for emacs-org MCP

## Core Principle

**ALWAYS use emacs-org MCP tools instead of direct file manipulation (Read/Edit/Write) for tasks.org and journal files.**

## Why Use MCP Tools?

1. **Automatic formatting:** Ensures correct org-mode syntax
2. **Section management:** Tasks placed in correct sections automatically
3. **Status handling:** DONE tasks automatically move to Completed section
4. **File creation:** Journal files created with proper headers if needed
5. **Safer operations:** Reduces risk of corrupting org file structure
6. **Timestamp management:** Handles CREATED, MODIFIED, CLOSED automatically
7. **Progress tracking:** Updates progress cookies `[/]` automatically

## Task Management Tools

### list_tasks(section)
List all tasks in a section ("Tasks" or "Completed Tasks")

**Use when:**
- Need to see all active or completed tasks
- Checking for duplicate tasks before creating new ones
- Getting overview of work in progress

### get_task(identifier)
Get a specific task by identifier (#+NAME, ticket ID like "GH-28", or headline substring)

**Use when:**
- Need complete task details
- Preparing to update a task
- Checking task status

### create_task(section, task_entry)
Create a new task from org-formatted string

**Use when:**
- User requests new task
- Starting work on a new ticket/issue

**Process:**
1. Search for duplicates with `search_tasks` or `list_tasks`
2. Format complete task entry in org-mode (UUID auto-generated if not provided)
3. Call `create_task` with section and entry

**Note:** The `:ID:` property is automatically generated if you don't provide it.

### update_task(identifier, task_entry)
Update an existing task with new content

**Use when:**
- Updating task progress (checking off items)
- Marking task as DONE
- Adding notes or related PRs
- Modifying task description

**Automatic behaviors:**
- TODO→DONE: Moves to Completed section, sets CLOSED timestamp
- DONE→TODO: Moves to Tasks section, clears CLOSED timestamp
- MODIFIED timestamp updated automatically

### move_task(identifier, from_section, to_section)
Move task between sections without modifying content

**Use when:**
- Need to relocate task without changing status
- Rarely needed (use `update_task` with status change instead)

### search_tasks(query)
Search tasks by keyword across all sections

**Use when:**
- Finding tasks related to a topic
- Checking for existing work before creating tasks
- Locating task by partial name

## Journal Management Tools

### list_journal_entries(date)
List all entries for a specific date

**Use when:**
- Checking what's already logged today
- Avoiding duplicate entries
- Reviewing day's work

### get_journal_entry(date, identifier)
Get specific entry by time (HH:MM) or headline

**Use when:**
- Need to read specific entry details
- Preparing to update an entry

### create_journal_entry(date, time, headline, content, tags)
Create a new journal entry

**Use when:**
- User explicitly requests logging work
- End of session (create `:daily_summary:` entry)
- Significant milestone reached (with user confirmation)

**IMPORTANT:** Always use the current system time for the timestamp. Do NOT use arbitrary times. Omit the `time` parameter to let it default to current time, or explicitly use `datetime.now().strftime("%H:%M")`.

**Process:**
1. Check existing entries with `list_journal_entries` to avoid duplicates
2. Use current system time (not arbitrary times like "17:30")
3. Include ticket ID (GH-xxx) if applicable
4. Add PR link if relevant (use `gh pr view`)
5. Add task links using `[[file:~/org/tasks.org::#CUSTOM_ID][Display]]` format
6. Call `create_journal_entry` with current time or omit time parameter

### update_journal_entry(date, line_number, time, headline, content, tags)
Update an existing journal entry

**Use when:**
- Correcting or enhancing existing entry
- Adding forgotten details or links

**Note:** Requires line_number from `list_journal_entries`

### search_journal(query, days_back)
Search journal entries by keyword

**Use when:**
- Finding past work on a topic
- Reviewing recent activity
- Looking up when something was done

**Default:** Searches last 30 days

## Ediff Approval Workflow

When `EMACS_EDIFF_APPROVAL=true` is configured:
- Create/update operations automatically present changes in Emacs ediff
- User can review and edit changes before approving
- No special workflow instructions needed - approval is handled automatically
- Changes appear side-by-side in new Emacs frame
- User approves with `C-c C-c` or rejects with `C-c C-k`

## Common Workflows

### Creating a Task for GitHub Issue
```
1. search_tasks("GH-123") - Check if task exists
2. create_task(section="Tasks", task_entry="...") - UUID auto-generated
```

### Marking Task Complete
```
1. get_task("GH-123") - Get current task
2. Modify status to DONE, update content
3. update_task("GH-123", task_entry="...") - Auto-moves to Completed
```

### Logging Work with Task Links
```python
from datetime import date, datetime

# 1. Check existing entries
list_journal_entries(date.today())

# 2. Create entry with current time
create_journal_entry(
    date=date.today(),
    time=datetime.now().strftime("%H:%M"),  # Use actual current time
    headline="Work on authentication",
    content=(
        "- Progress on [[file:~/org/tasks.org::#task-gh-127][GH-127]]\n"
        "- Completed two subtasks"
    ),
    tags=[]
)
```

### Logging Work at End of Day
```python
from datetime import date, datetime

# 1. Check existing entries
list_journal_entries(date.today())

# 2. Create summary with current time
create_journal_entry(
    date=date.today(),
    time=datetime.now().strftime("%H:%M"),  # Use actual current time
    headline="Summary of work",
    content=(
        "- Completed [[file:~/org/tasks.org::#task-gh-127][GH-127]]\n"
        "- PRs: [[https://github.com/org/repo/pull/221][#221]]"
    ),
    tags=["daily_summary"]
)
```

## Best Practices

1. **Always check for duplicates** before creating tasks or journal entries
2. **Use search tools** to find existing work
3. **Provide complete org format** when creating/updating tasks
4. **Include ticket IDs** (GH-xxx) in both tasks and journal entries
5. **Link journal entries to tasks** using org-mode links for traceability
6. **Link to multiple PRs** when a journal entry involves several pull requests
7. **Use progress tracking** with `*** Task items [/]` sections
8. **Keep journal entries focused** on outcomes and decisions
9. **Batch related work** into single journal entries
10. **Let timestamps auto-manage** - don't manually edit CREATED/MODIFIED/CLOSED
11. **Use current time for journal entries** - always use actual system time, not arbitrary times
