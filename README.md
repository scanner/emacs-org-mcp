# Emacs Org-Mode MCP Server

An MCP (Model Context Protocol) server that enables Claude to manage Emacs org-mode task lists and journal entries.

I use emacs org-mode for organizing myself. This mainly revolves around two things: Using org's journal-mode for keeping journal entries that includes linking to jira tickets, github pr's, other local files, etc. `journa-mode` is an easy way to create journal entries on the fly with some context built it. I also use tasks.org as a `task list` of active tasks, and completed tasks. Over time completed tasks are filed in to an org mode archive to keep the file from growing unmanageable.

I have been leveraging claude to do simple book keeping and context linking of tasks and journal entries, as well as simply reminding me or actively suggesting when I should update a task or make a journal entry, complete with the context of what I worked on since the last journal entry. This has worked out very well for me. claude was surprisingly able to work with org-mode files and keep things in the proper structure and formatting. However, as these files grow, and it has to read the entire file, it is going to hit token limits and it has to start doing tricks to read only part of the file. I wondered if a MCP dedicated to making it easier for claude to work with org-mode files and journal-mode journal entries would help, and indeed it does.

## Token Efficiency

Using an MCP reduces token usage compared to direct file manipulation with Read/Edit tools:

| Operation | Without MCP (Read/Edit) | With MCP |
|-----------|------------------------|----------|
| Find a task | Read entire `tasks.org` (could be 1000+ lines) | Returns only the matching task |
| Search tasks | Read file, Claude parses | Returns only matching results |
| List tasks | Read entire file | Returns structured list |
| Update task | Read file, generate Edit | Send task content, get confirmation |

**Where you save tokens:**

1. **Input tokens** - The raw file contents never enter the conversation context. A large `tasks.org` might be 50KB; the MCP returns only the relevant task (maybe 500 bytes).
2. **Output tokens** - Claude doesn't need to generate Edit tool calls with careful string matching. It just passes parameters to the MCP.
3. **Context accumulation** - Over a long conversation, Read operations accumulate in context. MCP responses are typically much smaller.

**Where savings are minimal:**

- **Creating new content** - Claude still generates the org-mode formatted task/entry text to pass to the MCP.
- **Small files** - If `tasks.org` is only 20 lines, the difference is negligible (my tasks.org is over 1,000 lines and wil still be growing.)

There is also the  benefit of reliability: The MCP handles org-mode parsing correctly every time, whereas Claude might occasionally make formatting errors with raw Edit operations.

## Features

- **Task Management** (`~/org/tasks.org`)
  - List, create, update, and search tasks
  - Optional visual approval via Emacs ediff (shows diff in Emacs, allows editing before applying)
  - Move tasks between Active and Completed sections
  - Automatic section movement when task status changes (TODO → DONE)
  - Find tasks by `:CUSTOM_ID:`, JIRA ticket ID, or headline

- **Journal Management** (`~/org/journal/`)
  - List, create, update, and search journal entries
  - Optional visual approval via Emacs ediff (shows diff in Emacs, allows editing before applying)
  - Support for tags (e.g., `:daily_summary:`)
  - Date-based file organization (YYYYMMDD format)

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for package management
- Emacs org-mode files in `~/org/`

## Installation

```bash
# Clone or create the project directory
cd ~/projects/emacs-task-journal-mcp

# Install dependencies
uv sync
```

## Configuration

### Claude Desktop

**Prerequisites:**

1. **Ensure `uv` is in your PATH.** Claude Desktop spawns processes without a login shell, so it may not inherit your shell's PATH modifications. You can either:
   - Use the full path to `uv` in the configuration (e.g., `/Users/yourname/.local/bin/uv`)
   - Or add `uv` to a system-wide PATH location

2. **Create the virtual environment first.** Before configuring Claude Desktop, run:
   ```bash
   cd /path/to/emacs-task-journal-mcp
   make sync   # or: uv sync
   ```
   This creates the `.venv` directory with all dependencies installed.

**Configuration:**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "emacs-org": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": [
        "--directory", "/path/to/emacs-task-journal-mcp",
        "run", "server.py"
      ],
      "env": {
        "ORG_DIR": "/path/to/org",
        "JOURNAL_DIR": "/path/to/org/journal",
        "ACTIVE_SECTION": "Tasks",
        "COMPLETED_SECTION": "Completed Tasks"
      }
    }
  }
}
```

> **Note:** Replace `/Users/yourname/.local/bin/uv` with the actual path to your `uv` binary. You can find it by running `which uv` in your terminal. If `uv` is reliably in your PATH, you can use just `"uv"` as the command.

### Claude Code

Add to user scope (available across all projects):

```bash
claude mcp add --scope user emacs-org \
  -- uv --directory /path/to/emacs-task-journal-mcp run server.py
```

Or use the Makefile:

```bash
make mcp-install
```

Or edit `~/.claude.json`:

```json
{
  "mcpServers": {
    "emacs-org": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/emacs-task-journal-mcp",
        "run", "server.py"
      ]
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORG_DIR` | `~/org` | Base org directory |
| `JOURNAL_DIR` | `$ORG_DIR/journal` | Journal files directory |
| `ACTIVE_SECTION` | `Tasks` | Section name for active/TODO tasks |
| `COMPLETED_SECTION` | `Completed Tasks` | Section name for completed/DONE tasks |
| `HIGH_LEVEL_SECTION` | `High Level Tasks (in order)` | Section name for the high-level task checklist |
| `EMACS_EDIFF_APPROVAL` | `false` | Enable visual approval via Emacs ediff (`true`/`1`/`yes` to enable) |
| `EMACSCLIENT_PATH` | _(searches PATH)_ | Custom path to `emacsclient` executable (optional) |

## Ediff Approval Feature

When `EMACS_EDIFF_APPROVAL=true` is set, task and journal create/update operations will present changes visually in Emacs using ediff before applying them. This provides a more interactive approval workflow compared to text-based previews.

**Features:**
- Visual side-by-side diff in Emacs
- Edit the proposed changes before accepting
- Present in a new Emacs frame (doesn't disrupt your existing windows)
- Context-specific filenames for easy identification (e.g., `old-gh-127.org`, `new-20250107-1430.org`)

**Setup:**

1. **Place `emacs_ediff.el` in the project root** (already included)

2. **Enable the feature** by setting the environment variable:
   ```json
   {
     "mcpServers": {
       "emacs-org": {
         "env": {
           "EMACS_EDIFF_APPROVAL": "true",
           "EMACSCLIENT_PATH": "/path/to/emacsclient"  // optional
         }
       }
     }
   }
   ```

3. **Ensure Emacs is running** - The MCP server communicates with Emacs via `emacsclient`

**Usage:**

When Claude calls a create or update operation:

1. A new Emacs frame opens with:
   - Side-by-side diff: Buffer A (left, current) vs Buffer B (right, proposed)
   - Control buffer below with ediff controls
2. You can navigate diffs and edit Buffer B (the new content)
3. From the control buffer, make your decision:
   - `C-c C-y` - Approve changes (applies changes)
   - `C-c C-k` - Reject changes (no modifications)
   - `q` - Quit (approves by default)
4. The frame and all buffers close automatically after your decision

**Notes:**

- Controls (`C-c C-y`, `C-c C-k`) only work in the control buffer
- You can save edits to Buffer B with `C-x C-s` while working
- If `emacsclient` is not found or Emacs is not running, operations fall back to auto-approve (no blocking)
- The `emacs_ediff.el` file is auto-loaded on first use
- Each operation uses temp files with descriptive names based on the task/journal context (e.g., `old-gh-127.org`, `new-20250110-1430.org`)

## Configuring CLAUDE.md

To instruct Claude to use this MCP server for task and journal management, add the following to your `~/.claude/CLAUDE.md` file.

### MCP Tool Names

When the MCP server is registered as `emacs-org`, Claude sees these tools (12 total):

| MCP Tool Name | Description |
|---------------|-------------|
| `mcp__emacs-org__list_tasks` | List tasks in a section |
| `mcp__emacs-org__get_task` | Get a task by identifier |
| `mcp__emacs-org__create_task` | Create a new task |
| `mcp__emacs-org__update_task` | Update a task (auto-moves on DONE) |
| `mcp__emacs-org__move_task` | Move task between sections |
| `mcp__emacs-org__search_tasks` | Search tasks by keyword |
| `mcp__emacs-org__list_journal_entries` | List entries for a date |
| `mcp__emacs-org__get_journal_entry` | Get a journal entry |
| `mcp__emacs-org__create_journal_entry` | Create a journal entry |
| `mcp__emacs-org__update_journal_entry` | Update a journal entry |
| `mcp__emacs-org__search_journal` | Search journal entries |

### Example CLAUDE.md Section

Add this near the top of your `~/.claude/CLAUDE.md`:

```markdown
## MCP Server for Tasks and Journal

**IMPORTANT**: Use the `emacs-org` MCP server tools for ALL task and journal operations instead of direct file manipulation with Read/Edit tools.

### Available MCP Tools

**Task Management** (for `~/org/tasks.org`):
- `mcp__emacs-org__list_tasks` - List tasks in a section ("Tasks" or "Completed Tasks")
- `mcp__emacs-org__get_task` - Get a task by identifier
- `mcp__emacs-org__create_task` - Create a new task in a section
- `mcp__emacs-org__update_task` - Update an existing task (automatically moves to Completed if status=DONE)
- `mcp__emacs-org__move_task` - Move a task between sections
- `mcp__emacs-org__search_tasks` - Search tasks by keyword across all sections

**Journal Management** (for `~/org/journal/YYYYMMDD`):
- `mcp__emacs-org__list_journal_entries` - List entries for a date
- `mcp__emacs-org__get_journal_entry` - Get a journal entry
- `mcp__emacs-org__create_journal_entry` - Create a new journal entry
- `mcp__emacs-org__update_journal_entry` - Update an existing journal entry
- `mcp__emacs-org__search_journal` - Search journal entries by keyword (with days_back limit)

### When to Use MCP Tools

- **Always prefer MCP tools** over Read/Edit for tasks.org and journal files
- MCP tools handle org-mode formatting, file creation, and section management automatically
- The tools ensure proper structure and avoid formatting errors

### Ediff Approval

When `EMACS_EDIFF_APPROVAL=true` is set:
- Create and update operations automatically present changes in Emacs ediff
- User can review and edit changes before approving
- No special workflow instructions needed - approval is handled automatically

### Task Entry Format for MCP

When creating tasks via `create_task`, provide the task content as an org-mode string:
```

````markdown
```org
** TODO GH-28 Task description
:PROPERTIES:
   :ID:       UUID-GENERATED-AUTOMATICALLY
   :CUSTOM_ID: task-gh-28
   :CREATED:  <YYYY-MM-DD DDD HH:MM>  (set automatically on creation)
   :MODIFIED: [YYYY-MM-DD DDD HH:MM]  (updated automatically on modification)
   :CLOSED:   <YYYY-MM-DD DDD HH:MM>  (set automatically when marked DONE)
:END:

*** Task items [/]
- [ ] First item
- [ ] Second item
```
````

**Timestamp Properties** (managed automatically by the MCP server):
- `:CREATED:` - Active timestamp `<>` set when task is first created
- `:MODIFIED:` - Inactive timestamp `[]` updated on every task update
- `:CLOSED:` - Active timestamp `<>` set when task is marked DONE (standard org-mode property)
  - Preserved when updating a DONE task that stays DONE
  - Cleared when reopening a DONE task back to TODO

Note: Timestamps are naive (no timezone) as org-mode does not support timezone information.

```markdown
### Journal Entry Parameters

When creating journal entries via `create_journal_entry`:
- `target_date`: Date object or ISO string (e.g., "2025-12-22")
- `time_str`: Time in HH:MM format (e.g., "14:30")
- `headline`: Entry headline (include ticket ID if relevant)
- `content`: Bullet point content (e.g., "- Did something\n- Did another thing")
- `tags`: Optional list of tags (e.g., ["daily_summary"])
```

### Implementation Notes Section

If you have an "Implementation Notes for Claude" section, update it to reference MCP tools:

```markdown
## Implementation Notes for Claude

**Use MCP tools for all task and journal operations** (see "MCP Server for Tasks and Journal" section above).

When creating journal entries:
1. Use `mcp__emacs-org__get_journal_entries` to check for existing entries and avoid duplicates
2. Use `mcp__emacs-org__create_journal_entry` to add new entries
3. Use current system time for the HH:MM timestamp
4. Check git branch for ticket ID extraction
5. The MCP tools handle org-mode formatting automatically

When managing tasks:
1. Use `mcp__emacs-org__find_task` to locate existing tasks before creating new ones
2. Use `mcp__emacs-org__create_task` for new tasks
3. Use `mcp__emacs-org__update_task` to modify tasks or mark them DONE (auto-moves to Completed)
4. The MCP tools handle section management and formatting automatically
```

### Why Use MCP Tools Instead of Read/Edit?

1. **Automatic formatting** - The MCP tools ensure correct org-mode syntax
2. **Section management** - Tasks are automatically placed in the correct section
3. **Status handling** - Marking a task DONE automatically moves it to Completed Task List
4. **File creation** - Journal files are created with proper headers if they don't exist
5. **Safer operations** - Reduces risk of corrupting org file structure

## Testing

### Run Tests

```bash
# Run all pytest tests
make test

# Test MCP server responds to tools/list
make test-mcp
```

### Manual Testing

```bash
# List available tools (requires MCP initialization handshake)
(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'; \
 echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'; \
 echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | \
 uv run server.py 2>/dev/null | tail -1 | python3 -m json.tool
```

## Available Tools

### Task Tools

| Tool | Description |
|------|-------------|
| `list_tasks` | List all tasks in a section (Active/Completed) |
| `get_task` | Get a task by identifier (name, ticket ID, or headline) |
| `create_task` | Create a new task with full org-formatted content |
| `update_task` | Update a task; auto-moves if status changes |
| `preview_task_update` | Preview task changes (shows diff without modifying file) |
| `move_task` | Move a task between sections |
| `search_tasks` | Search tasks by query string |

### Journal Tools

| Tool | Description |
|------|-------------|
| `list_journal_entries` | List entries for a specific date |
| `get_journal_entry` | Get an entry by time or headline |
| `create_journal_entry` | Create a new journal entry |
| `update_journal_entry` | Update an existing entry |
| `preview_journal_update` | Preview entry changes (shows diff without modifying file) |
| `search_journal` | Search entries across recent days |

## Task Format

Tasks follow the structure defined in `~/.claude/CLAUDE.md`:

### File Structure

```org
* High Level Tasks (in order) [1/3]
- [X] Fix authentication edge cases
- [ ] Migrate posture rules to SemVer
- [ ] Expose categories in API

* Tasks

** TODO GH-221 Migrate posture rules to SemVer
:PROPERTIES:
   :ID:       A1B2C3D4-E5F6-7890-ABCD-EF1234567890
   :CUSTOM_ID: task-gh-221
:END:

*** Description

Migrate all posture rules from CalVer to SemVer versioning.

*** Related PRs
- [[https://github.com/org/repo/pull/221][#221 - Initial migration]]

*** Task items [1/3]
- [X] Create migration plan
- [ ] Update all rule definitions
- [ ] Run full test suite

** TODO GH-450 Expose categories in API
:PROPERTIES:
   :ID:       B2C3D4E5-F6A7-8901-BCDE-F23456789012
   :CUSTOM_ID: task-gh-450
:END:

*** Description

Add API endpoints for product categories.

*** Related PRs
- [[https://github.com/org/repo/pull/450][#450 - Add categories endpoint]]

*** Task items [2/4]
- [X] Design API schema
- [X] Implement categories model
- [ ] Add API endpoints
- [ ] Write integration tests

* Completed Tasks

** DONE GH-4100 Fix authentication edge cases
:PROPERTIES:
   :ID:       C3D4E5F6-A7B8-9012-CDEF-345678901234
   :CUSTOM_ID: task-gh-4100
:END:

*** Description

Fixed edge cases in authentication flow.

*** Related PRs
- [[https://github.com/org/api/pull/4100][#4100 - Auth fixes]]

*** Task items [2/2]
- [X] Identify edge cases
- [X] Add test coverage
```

### Task Hierarchy

| Level | Format | Description |
|-------|--------|-------------|
| `*` | Section headings | `High Level Tasks (in order)`, `Tasks`, `Completed Tasks` |
| `**` | Major task | `** TODO/DONE <description>` |
| `:PROPERTIES:` | Properties drawer | Contains `:ID:` (UUID) and `:CUSTOM_ID:` (stable link target) |
| `***` | Subsections | `Description`, `Related PRs`, `Task items [/]`, `Notes` |
| `****` | Sub-sections | Nested content within subsections |

### Task States

| State | Description |
|-------|-------------|
| `TODO` | Active task in progress |
| `DONE` | Task completed |

### Named Targets

Every task includes a `:CUSTOM_ID:` property in the `:PROPERTIES:` drawer for stable linking:

- Format: `task-<ticket-id>` or `task-<short-slug>`
- Examples: `task-gh-4049`, `task-auth-fix`
- Used for org-mode file links: `[[file:~/org/tasks.org::#task-gh-4049][gh-4049 task]]`

### Task Items (Checklists)

```org
*** Task items [2/4]
- [X] Completed item
- [X] Another completed item
- [ ] Pending item
- [ ] Another pending item
```

- Progress cookie `[/]` auto-updates to show `[completed/total]`
- Use `[X]` for completed, `[ ]` for pending

### Related PRs

```org
*** Related PRs
- [[https://github.com/org/repo/pull/123][#123 - Description of PR]]
- [[https://github.com/org/repo/pull/125][#125 - Follow-up fixes]]
```

Multiple PRs per task are common. Use org-mode link format: `[[url][#number - description]]`

## Journal Format

Journal entries follow `org-journal` conventions:

```org
* 2025-01-15

** 14:30 GH-221 [[https://github.com/org/repo/pull/221][#221]] Completed migration :daily_summary:
- Migrated posture rules from CalVer to SemVer
- PR approved and merged to master
```

### File Naming

Journal files are stored in `$JOURNAL_DIR` with names based on the date. Both `YYYYMMDD` and `YYYYMMDD.org` formats are supported:

- Files are detected regardless of whether they have the `.org` extension
- New files match the existing convention: if any `.org` files exist, new files use `.org`; otherwise, no extension is used

## License

MIT
