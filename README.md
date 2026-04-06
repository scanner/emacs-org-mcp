# Emacs Org-Mode MCP Server

An MCP (Model Context Protocol) server that enables Claude to manage Emacs
org-mode task lists, journal entries, and projects.

I use Emacs org-mode for organising myself. This mainly revolves around three
things: `tasks.org` as a tracked task list (active and completed), a
`journal/` directory of daily journal files, and `projects/` — one file per
project — for longer-running work. Over time I have been leveraging Claude for
bookkeeping and context-linking: reminding me to update a task, suggesting a
journal entry, or noting what I worked on since the last summary.

Claude was surprisingly capable at working with org-mode files directly, but
as those files grew it started hitting token limits. A dedicated MCP solves
that: tools return only the data Claude needs, structure is maintained
correctly, and there is a built-in visual approval step via Emacs ediff before
any write lands on disk.

## Token Efficiency

| Operation    | Without MCP (Read/Edit)               | With MCP                              |
|--------------|---------------------------------------|---------------------------------------|
| Find a task  | Read entire `tasks.org` (1000+ lines) | Returns only the matching task        |
| Search tasks | Read file, Claude parses              | Returns only matching results         |
| List tasks   | Read entire file                      | Returns structured list               |
| Update task  | Read file, generate Edit              | Send task content, ediff for approval |

**Input tokens** — raw file contents never enter the conversation context.
**Output tokens** — Claude passes parameters to the MCP rather than generating
careful string-matched Edit calls.
**Context accumulation** — MCP responses are much smaller than repeated file
reads over a long conversation.

There is also a reliability benefit: the MCP handles org-mode parsing correctly
every time, whereas Claude occasionally makes formatting errors with raw Edit
operations.

## Features

- **Task Management** (`~/org/tasks.org`)
  - List, create, update, search, and move tasks
  - Automatic section movement when status changes (`TODO` → `DONE`)
  - Find tasks by `:CUSTOM_ID:`, ticket ID (e.g. `GH-123`), or headline
  - Auto-maintained High Level Tasks checklist
  - Visual approval via Emacs ediff before writes

- **Journal Management** (`~/org/journal/`)
  - List, create, update, and search journal entries
  - Date-based file organisation (`YYYYMMDD` format)
  - Tag support (`:daily_summary:`, `:meeting:`, etc.)
  - Visual approval via Emacs ediff before writes

- **Project Management** (`~/org/projects/`)
  - One org file per project (`<slug>.org`)
  - List, create, update, and search projects
  - Section-level updates (avoids rewriting entire files)
  - Cross-linking between projects, tasks, and journal entries
  - Auto-maintained `index.org` with all projects grouped by status
  - Status values: `active`, `planning`, `on-hold`, `completed`

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for package management
- Emacs org-mode files in `~/org/`

## Installation

```bash
cd ~/projects/emacs-org-mcp

# Install dependencies
uv sync
```

## Configuration

### Claude Desktop

**Prerequisites:**

1. **Ensure `uv` is in your PATH.** Claude Desktop spawns processes without a
   login shell and may not inherit your shell's PATH. Use the full path to `uv`
   (e.g. `/Users/yourname/.local/bin/uv`) or add it to a system-wide location.

2. **Create the virtual environment first:**
   ```bash
   cd /path/to/emacs-org-mcp
   make sync   # or: uv sync
   ```

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "emacs-org": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": [
        "--directory", "/path/to/emacs-org-mcp",
        "run", "server.py"
      ],
      "env": {
        "ORG_DIR": "/path/to/org"
      }
    }
  }
}
```

> **Note:** Replace `/Users/yourname/.local/bin/uv` with the output of
> `which uv`. If `uv` is reliably in your PATH you can use just `"uv"`.

### Claude Code

Add to user scope (available across all projects):

```bash
claude mcp add --scope user emacs-org \
  -- uv --directory /path/to/emacs-org-mcp run server.py
```

Or use the Makefile:

```bash
make mcp-install
```

Or edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "emacs-org": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/emacs-org-mcp",
        "run", "server.py"
      ]
    }
  }
}
```

## Environment Variables

All settings can be overridden via environment variables or command-line flags:

| Variable / Flag | Default | Description |
|-----------------|---------|-------------|
| `ORG_DIR` / `--org-dir` | `~/org` | Base org directory |
| `JOURNAL_DIR` / `--journal-dir` | `$ORG_DIR/journal` | Journal files directory |
| `PROJECTS_DIR` / `--projects-dir` | `$ORG_DIR/projects` | Project files directory |
| `ACTIVE_SECTION` / `--active-section` | `Tasks` | Section name for active/TODO tasks |
| `COMPLETED_SECTION` / `--completed-section` | `Completed Tasks` | Section name for completed/DONE tasks |
| `HIGH_LEVEL_SECTION` / `--high-level-section` | `High Level Tasks (in order)` | Section name for the high-level task checklist |
| `EMACS_EDIFF_APPROVAL` / `--ediff-approval` / `--no-ediff-approval` | `true` | Visual approval via Emacs ediff |
| `EMACSCLIENT_PATH` / `--emacsclient-path` | _(searches PATH)_ | Custom path to `emacsclient` (optional) |

## Ediff Approval

By default, all create and update operations present changes visually in Emacs
using ediff before applying them. A new Emacs frame opens with a side-by-side
diff; you can edit the proposed content (Buffer B) before approving.

**Controls** (from the ediff control buffer):

| Key       | Action                     |
|-----------|----------------------------|
| `C-c C-y` | Approve — apply changes    |
| `C-c C-k` | Reject — discard changes   |
| `q`       | Quit — approves by default |

The frame and all buffers close automatically after your decision. If
`emacsclient` is not available or Emacs is not running, the server falls back
to auto-approve.

**To disable ediff approval:**

```bash
uv run server.py --no-ediff-approval
# or set EMACS_EDIFF_APPROVAL=false in the MCP server env
```

## Available Tools

### Task Tools (7)

| Tool           | Description                                                   |
|----------------|---------------------------------------------------------------|
| `list_tasks`   | List all tasks in a section (`Tasks` or `Completed Tasks`)    |
| `get_task`     | Get a task by `:CUSTOM_ID:`, ticket ID, or headline substring |
| `create_task`  | Create a new task from a complete org-formatted string        |
| `update_task`  | Replace a task; auto-moves between sections on status change  |
| `move_task`    | Move a task between sections without changing content         |
| `search_tasks` | Search tasks by keyword across all sections                   |

### Journal Tools (5)

| Tool                   | Description                                          |
|------------------------|------------------------------------------------------|
| `list_journal_entries` | List entries for a date (defaults to today)          |
| `get_journal_entry`    | Get an entry by time (`HH:MM`) or headline substring |
| `create_journal_entry` | Create a new journal entry                           |
| `update_journal_entry` | Update an existing entry                             |
| `search_journal`       | Search entries across recent days                    |

### Project Tools (7)

| Tool                       | Description                                                    |
|----------------------------|----------------------------------------------------------------|
| `list_projects`            | List all projects, optionally filtered by status               |
| `get_project`              | Get a project by slug, `:CUSTOM_ID:`, or title substring       |
| `create_project`           | Create a new project file from a complete org-formatted string |
| `update_project`           | Update project sections, properties, headline, or tags         |
| `search_projects`          | Search across all project files                                |
| `link_task_to_project`     | Add a task link to a project's Related Tasks section           |
| `regenerate_project_index` | Rebuild `index.org` from all project files                     |

### Other

| Tool             | Description                              |
|------------------|------------------------------------------|
| `diagnostic_env` | Show server configuration and file paths |

## MCP Resources

The server exposes resources that Claude can read directly for format
documentation and live data:

| Resource URI                       | Description                                 |
|------------------------------------|---------------------------------------------|
| `emacs-org://guide/task-format`    | Task format specification                   |
| `emacs-org://guide/journal-format` | Journal entry format specification          |
| `emacs-org://guide/project-format` | Project file format and cross-linking guide |
| `org://tasks/active`               | Live view of active tasks                   |
| `org://tasks/completed`            | Live view of completed tasks                |
| `org://journal/today`              | Today's journal entries                     |
| `org://projects/index`             | All projects grouped by status              |

## Configuring CLAUDE.md

Add this section to your `~/.claude/CLAUDE.md` to instruct Claude to use the
MCP server for all org-mode operations:

```markdown
## Emacs Org-Mode (Journal, Tasks, Projects)

**CRITICAL: Always use the `mcp__emacs-org__*` MCP tools** for all journal,
task, and project operations. Never use Read/Write/Edit tools or bash commands
directly on these files.

### Format Reference

The MCP server exposes authoritative format guides as resources:
- `emacs-org://guide/journal-format`
- `emacs-org://guide/task-format`
- `emacs-org://guide/project-format`
```

Claude will fetch the detailed format documentation from those resources when
needed, so you do not need to duplicate it in `CLAUDE.md`.

## Testing

```bash
# Run all tests
make test

# Verify the server responds to tools/list
make test-mcp
```

## License

MIT
