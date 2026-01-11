# Emacs Org-Mode MCP Server

## Project Overview

This is an MCP (Model Context Protocol) server that enables Claude (via Claude Desktop, Claude Code, or Claude CLI) to manage Emacs org-mode task lists and journal entries without resorting to shell commands or ad-hoc Python scripts.

### Goals

1. Provide a clean, well-defined interface for manipulating `~/org/tasks.org`
2. Provide a clean interface for managing `~/org/journal/` entries
3. Use `orgmunge` for robust org-mode AST manipulation (tasks)
4. Follow the task and journal formats defined in `~/.claude/CLAUDE.md`

### What This Replaces

Previously, Claude would use `cat` to read org files and write Python scripts to manipulate them. This MCP provides explicit, safe tools for these operations.

## Tech Stack

- **Python 3.13+**
- **uv** for package management (not pip/venv directly)
- **MCP SDK** (`mcp` package) for the Model Context Protocol server
- **orgmunge** for parsing and manipulating org-mode files (tasks)
- Manual parsing for journal files (simpler flat structure)

## Running and Testing

```bash
# Install dependencies (including dev tools)
# NOTE: Requires gcloud auth - run `gcloud auth login` first if needed
make setup

# Run the server (for testing with stdin/stdout)
uv run server.py

# Test with JSON-RPC messages
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | uv run server.py
make test-mcp  # Shortcut for the above
```

## Linting

**IMPORTANT**: Run linting after all code modifications to ensure code quality.

```bash
# Run all linters (black, isort, ruff, mypy, pre-commit hooks)
# NOTE: Requires gcloud auth - run `gcloud auth login` first if needed
make lint

# Run individual linters
make black   # Code formatting
make isort   # Import sorting
make ruff    # Fast Python linter
make mypy    # Type checking
```

Linting is configured via:
- `.pre-commit-config.yaml` - Pre-commit hook definitions
- `pyproject.toml` - Tool configurations (black, isort, ruff, mypy)

Line length is set to 100 characters. E501 (line too long) is ignored in ruff since black handles formatting.

## Project Structure

```
emacs-task-journal-mcp/
├── CLAUDE.md              # This file
├── README.md              # User documentation
├── pyproject.toml         # uv/Python project config
├── uv.lock                # Lock file
├── server.py              # Main MCP server implementation
├── emacs_ediff.el         # Emacs Lisp for ediff approval workflow
└── manual_test_ediff.py   # Manual test script for ediff approval
```

## Key Design Decisions

### Task Operations Use orgmunge

The `orgmunge` library provides proper AST-based manipulation of org files. This is important because:
- Preserves file structure, comments, and formatting
- Handles edge cases in org syntax correctly
- Supports proper insertion/removal of headings

Reference implementation: `org_munge.py` in project root shows patterns for using orgmunge.

### Journal Operations Use Manual Parsing

Journal files have a simpler structure (`* date` heading with `** time entry` children) that doesn't require full AST manipulation. Manual parsing is sufficient and avoids complexity.

### Tasks Accept Complete Org-Formatted Strings

The `create_task` and `update_task` tools accept `task_entry` as a complete org-formatted string rather than individual fields. This is because:
- Claude already knows how to write proper org format per `~/.claude/CLAUDE.md`
- Task structure is complex (subsections, code blocks, links) and hard to decompose
- orgmunge can parse the string and insert it correctly

### Automatic Section Movement

When `update_task` is called and the TODO state changes (e.g., `TODO` → `DONE`), the task automatically moves to the appropriate section (Active → Completed or vice versa).

### Ediff Approval (Optional)

When `EMACS_EDIFF_APPROVAL=true` is set, create/update operations present changes in Emacs ediff before applying them:
- Opens a new Emacs frame with side-by-side diff (Buffer A: current, Buffer B: proposed)
- Control buffer appears below the diff buffers in the same frame
- User can edit the proposed changes (Buffer B) before accepting
- Approval keys (in control buffer only):
  - `C-c C-y` - Approve changes
  - `C-c C-k` - Reject changes
  - `q` - Quit (approves by default)
- Frame and buffers automatically close after decision
- Falls back to auto-approve if emacsclient unavailable
- Implementation: `emacs_ediff.el` + Python helpers in `server.py`

## File Locations

| File | Path | Description |
|------|------|-------------|
| Tasks | `~/org/tasks.org` | Task list with Tasks/Completed Tasks sections |
| Journal | `~/org/journal/YYYYMMDD` | Daily journal files (with or without `.org` extension) |

## Configuration

All settings can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ORG_DIR` | `~/org` | Base org directory |
| `JOURNAL_DIR` | `$ORG_DIR/journal` | Journal files directory |
| `ACTIVE_SECTION` | `Tasks` | Section name for active/TODO tasks |
| `COMPLETED_SECTION` | `Completed Tasks` | Section name for completed/DONE tasks |
| `HIGH_LEVEL_SECTION` | `High Level Tasks (in order)` | Section name for the high-level task checklist |
| `EMACS_EDIFF_APPROVAL` | `false` | Enable visual approval via Emacs ediff (`true`/`1`/`yes` to enable) |
| `EMACSCLIENT_PATH` | _(searches PATH)_ | Custom path to `emacsclient` executable (optional) |

## Task Format Reference

Tasks live under `* Tasks` or `* Completed Tasks` sections (configurable via env vars).
There is also a `* High Level Tasks (in order)` section with a checklist overview.

```org
* High Level Tasks (in order) [1/2]
- [X] Completed task description
- [ ] Active task description

* Tasks

** TODO GH-28 Task description here
:PROPERTIES:
   :ID:       C79031AC-94FE-4FDD-BBBF-7D3EE1A881E9
   :CUSTOM_ID: task-gh-28
   :CREATED:  <2025-12-26 Fri 01:45>
   :MODIFIED: [2025-12-26 Fri 02:30]
:END:

*** Description

Description of the task and its purpose.

*** Related Issues
- [[https://github.com/org/repo/issues/28][GH-28 - Issue title]]

*** Related PRs
- [[https://github.com/org/repo/pull/123][#123 - PR description]]

*** Task items [1/3]
- [X] Completed item
- [ ] Pending item
- [ ] Another pending item

*** Notes

Additional notes, code examples, etc.

* Completed Tasks

** DONE GH-27 Previous task
:PROPERTIES:
   :ID:       A1B2C3D4-E5F6-7890-ABCD-EF1234567890
   :CUSTOM_ID: task-gh-27
   :CREATED:  <2025-12-20 Fri 10:00>
   :MODIFIED: [2025-12-25 Wed 14:30]
   :CLOSED:   <2025-12-25 Wed 14:30>
:END:
...
```

Key elements:
- `:PROPERTIES:` drawer immediately after heading with:
  - `:ID:` UUID for org-mode compatibility (auto-generated if not present)
  - `:CUSTOM_ID: task-<identifier>` for stable linking
  - `:CREATED:` Active timestamp `<>` set automatically when task is created
  - `:MODIFIED:` Inactive timestamp `[]` updated automatically on every modification
  - `:CLOSED:` Active timestamp `<>` set automatically when task is marked DONE (standard org-mode property)
    - Preserved when updating a DONE task that stays DONE
    - Cleared when reopening a DONE task back to TODO
- `*** Description` for task description
- `*** Task items [/]` with checkbox list (progress cookie auto-updates)
- Subsections at `***` level: Description, Related Issues, Related PRs, Task items, Notes
- Code blocks: `#+begin_src lang` / `#+end_src`

**Note on timestamps**: All timestamps are naive (no timezone) as org-mode does not support timezone information. Timestamps reflect the local timezone of the Emacs instance.

## Journal Format Reference

Journal files are named `YYYYMMDD` (no extension) in `~/org/journal/`:

```org
* 2025-01-15

** 14:30 GH-28 [[https://github.com/org/repo/pull/28][#28]] Completed migration :daily_summary:
- Bullet point detail
- Another detail

** 16:45 Fixed authentication bug
- Discovered during exploratory testing
- No ticket (ad-hoc work)
```

Key elements:
- Date heading: `* YYYY-MM-DD`
- Entry format: `** HH:MM [TICKET-ID] headline :tags:`
- Tags like `:daily_summary:` for filtering
- PR links inline: `[[url][#number]]`

## MCP Tools Implemented

### Task Tools

| Tool | Description |
|------|-------------|
| `list_tasks` | List all tasks in a section |
| `get_task` | Get task by identifier (#+NAME, ticket ID, or headline) |
| `create_task` | Create new task from org-formatted string |
| `update_task` | Update task; auto-moves if status changes |
| `move_task` | Move task between sections |
| `search_tasks` | Search tasks by query |

### Journal Tools

| Tool | Description |
|------|-------------|
| `list_journal_entries` | List entries for a date |
| `get_journal_entry` | Get entry by time or headline |
| `create_journal_entry` | Create new entry |
| `update_journal_entry` | Update existing entry |
| `search_journal` | Search entries across recent days |

## Code Style

- Use `match/case` statements instead of `if/elif/else` chains
- Type hints throughout (Python 3.13+ syntax: `list[str]`, `str | None`)
- Dataclasses for structured data (`Task`, `JournalEntry`)
- Async functions for MCP handlers (required by MCP SDK)

## Testing Checklist

When making changes, verify:

1. `list_tasks` returns tasks with correct structure
2. `get_task` finds tasks by #+NAME, ticket ID, and headline substring
3. `create_task` adds task to correct section
4. `update_task` preserves position when status unchanged
5. `update_task` moves task when status changes (TODO→DONE)
6. `move_task` works in both directions
7. Journal operations work with date-based file naming
8. Backups are created before file modifications

### Testing Ediff Approval

To manually test the ediff approval workflow:

```bash
# Test the ediff approval UI
EMACS_EDIFF_APPROVAL=true uv run manual_test_ediff.py
```

The test script:
- Automatically reloads `emacs_ediff.el` for development
- Opens ediff with sample task content (OAuth2 implementation)
- Tests approve/reject/quit workflows
- Reports the final decision and content

Expected behavior:
- New Emacs frame opens with side-by-side diff
- Control buffer appears below with instructions
- `C-c C-y` approves, `C-c C-k` rejects, `q` quits (approves)
- Frame closes automatically after decision

## Known Limitations

- No support for org-mode priorities (`[#A]`, `[#B]`, `[#C]`) in parsing (preserved in content)
- No support for scheduled/deadline timestamps in parsing (preserved in content)
- Journal files use manual parsing, not orgmunge
- No concurrent access protection (relies on single-user access pattern)

## Related Files

- `~/.claude/CLAUDE.md` - Main Claude instructions including task/journal format specs
- `~/org/tasks.org` - The actual tasks file
- `~/org/journal/` - Journal directory

## Dependencies

From `pyproject.toml`:
- `mcp>=1.0.0` - MCP SDK for server implementation
- `orgmunge>=0.3.1` - Org-mode AST manipulation

The `orgparse` dependency in pyproject.toml is not currently used and can be removed.
