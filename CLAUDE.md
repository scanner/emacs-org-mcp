# Emacs Org-Mode MCP Server

## Project Overview

This is an MCP (Model Context Protocol) server that enables Claude (via Claude Desktop, Claude Code, or Claude CLI) to manage Emacs org-mode task lists, journal entries, and projects without resorting to shell commands or ad-hoc Python scripts.

### Goals

1. Provide a clean, well-defined interface for manipulating `~/org/tasks.org`
2. Provide a clean interface for managing `~/org/journal/` entries
3. Provide project management via `~/org/projects/` individual project files
4. Use `orgmunge` for robust org-mode AST manipulation (tasks)
5. Follow the task, journal, and project formats defined in `~/.claude/CLAUDE.md`

### What This Replaces

Previously, Claude would use `cat` to read org files and write Python scripts to manipulate them. This MCP provides explicit, safe tools for these operations.

## Tech Stack

- **Python 3.13+**
- **uv** for package management (not pip/venv directly)
- **MCP SDK** (`mcp` package) for the Model Context Protocol server
- **orgmunge** for parsing and manipulating org-mode files (tasks)
- Manual parsing for journal files (simpler flat structure)
- Manual parsing for project files (one file per project)

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
# Run all linters (ruff check, ruff format, mypy, pre-commit hooks)
# NOTE: Requires gcloud auth - run `gcloud auth login` first if needed
make lint

# Run individual linters
make ruff-format  # Code formatting (replaces black + isort)
make ruff-check   # Linting
make mypy         # Type checking
```

Linting is configured via:
- `.pre-commit-config.yaml` - Pre-commit hook definitions
- `pyproject.toml` - Tool configurations (ruff, mypy)

Line length is set to 80 characters. E501 (line too long) is ignored in ruff since ruff format handles it.

## Project Structure

```
emacs-task-journal-mcp/
├── CLAUDE.md              # This file
├── README.md              # User documentation
├── pyproject.toml         # uv/Python project config
├── uv.lock                # Lock file
├── server.py              # Entry point
├── emacs_ediff.el         # Emacs Lisp for ediff approval workflow
├── manual_test_ediff.py   # Manual test script for ediff approval
├── mcp_server/            # Server implementation
│   ├── config.py          # Config dataclass and global state
│   ├── tools.py           # MCP tool definitions and dispatch
│   ├── resources.py       # MCP resource definitions and guide loading
│   ├── tasks.py           # Task CRUD, orgmunge ops, write guard
│   ├── journal.py         # Journal CRUD (manual parsing)
│   ├── orgmunge_patch.py  # Line-oriented fix for orgmunge's drawer lexer
│   ├── projects.py        # Project CRUD (manual parsing)
│   ├── properties.py      # Canonical :PROPERTIES: drawer format
│   ├── results.py         # Shared result envelope: detail levels, paging
│   ├── validation.py      # Heading-level validation, block escaping
│   ├── versioning.py      # Git auto-commit of org file changes
│   └── utils.py           # Timestamps, atomic file I/O, ediff bridge
├── resources/guides/      # MCP resource guide files
│   ├── task-format.md
│   ├── journal-format.md
│   └── project-format.md
└── tests/
    ├── conftest.py        # Shared fixtures and factories
    ├── test_config.py
    ├── test_ediff.py
    ├── test_factories.py
    ├── test_journal.py
    ├── test_projects.py
    ├── test_properties.py
    ├── test_resources.py
    ├── test_task_integrity.py  # Data-loss regression tests
    ├── test_tasks.py
    ├── test_validation.py
    └── test_versioning.py
```

## Key Design Decisions

### Task Operations Use orgmunge

The `orgmunge` library provides proper AST-based manipulation of org files. This is important because:
- Preserves file structure, comments, and formatting
- Handles edge cases in org syntax correctly
- Supports proper insertion/removal of headings

Reference implementation: `org_munge.py` in project root shows patterns for using orgmunge.

### Journal and Project Operations Use Manual Parsing

Journal files have a simpler structure (`* date` heading with `** time entry` children) that doesn't require full AST manipulation. Project files are one heading per file with level-2 sections. Both use manual parsing for simplicity.

### Tasks Accept Complete Org-Formatted Strings

The `create_task` and `update_task` tools accept `task_entry` as a complete org-formatted string rather than individual fields. This is because:
- Claude already knows how to write proper org format per `~/.claude/CLAUDE.md`
- Task structure is complex (subsections, code blocks, links) and hard to decompose
- orgmunge can parse the string and insert it correctly

### Automatic Section Movement

When `update_task` is called and the TODO state changes (e.g., `TODO` → `DONE`), the task automatically moves to the appropriate section (Active → Completed or vice versa).

### Structural Validation (`mcp_server/validation.py`)

Every document has a fixed root level and all topics must nest below it:

| Document | Root | Topics must be |
|----------|------|----------------|
| Task | `**` | `***` or deeper |
| Journal entry | `**` | `***` or deeper |
| Project file | `*` | `**` or deeper |

Submitted content that breaks this is **rejected** with a message naming the
offending line and its corrected form. This is a data-loss guard, not style
enforcement: orgmunge keeps only the first `**` heading of a task entry, so a
stray sibling silently discarded everything after it while reporting success.

Validation runs in `parse_task_entry`, `create_journal_entry`,
`update_journal_entry`, `create_project`, and `update_project` — the parser
boundary, so no tool path can bypass it.

Three distinct corruptions hide a heading from the org parser. All are
guarded against, and all have regression tests in
`tests/test_task_integrity.py`:

**Indented heading** (root cause of the 2026-08-23 data loss). A single leading
space turns `** TODO Task` into body text, so org folds the whole task —
drawer, subsections and all — into the *preceding* task's subtree. This
reproduces every reported symptom: `get_task` cannot find it, `list_tasks`
omits it positionally, and `search_tasks` for text unique to its body returns
the task *before* it. A full-replacement `update_task` on that preceding task
then overwrites the absorbed region and the task is destroyed.
`find_indented_headings()` detects these; note it requires **two or more**
stars, since a lone indented `*` is a legitimate org list bullet.

**Phantom heading.** orgmunge does not exempt `#+begin_src`/`#+begin_example`
blocks — a `* Tasks` line inside a block parses as a real level-1 heading and
re-parents every task after it. `escape_headings_in_blocks()` comma-escapes
such lines (`,* Tasks`), which is what Emacs itself does.

**False drawer** (root cause of the 2026-08-28 data loss). See
`mcp_server/orgmunge_patch.py`. Org decides every construct by the line it sits
on; orgmunge's drawer pattern `^\s*:[^:]+:.+?:(?:end|END):` does not — its `.+?`
crosses newlines because the lexer sets `re.DOTALL`, and its `[^:]+` crosses
them regardless, since a negated class matches `\n` unless `\n` is excluded.
Any body line whose
first non-blank character is a colon therefore opens a drawer running to the
next `:END:` *anywhere later in the file*, swallowing the headings in between.
A file with a hundred property drawers always has a later `:END:`, so the reach
is effectively unbounded. One fixed-width histogram line made `* Completed
Tasks` invisible: every DONE task under it was reported as active, the first
task below it was absorbed into the body of the task above, and rewriting that
task destroyed the heading. The patch makes the drawer token line-anchored and
unable to span a headline — the same convention `properties.py` already uses.
It verifies orgmunge still ships the known-broken pattern and refuses to start
if not, since a silently ineffective patch means losing data again.

### Write Integrity Guarantees (`mcp_server/tasks.py`)

- `write_tasks_org()` wraps every write to `tasks.org`. It scans the raw text
  before and after (via `scan_task_identities()`, deliberately **not** using
  orgmunge) and refuses the write if any task other than the named `target`
  would disappear. This holds regardless of *why* a task went missing.
- The same guard refuses any write that would drop a **section heading**
  (`scan_section_headings()`, also raw-text). A lost section need not take a
  task with it: when a swallowed region ends before the first task under a
  heading, every task identity still matches and only the heading dies. That is
  how `* Completed Tasks` was destroyed with the task guard already in place. A
  section's trailing progress cookie is ignored, since it is recounted while
  the section stays put.
- `write_file()` writes via temp file + atomic rename and retains the previous
  version as `<name>.bak`, so recovery never depends on an Emacs autosave.
- `find_unparsed_tasks()` reports tasks present in the file but invisible to
  the parser. `list_tasks` output and `find_task` "not found" errors surface
  these rather than silently omitting them.

### Canonical PROPERTIES Drawer (`mcp_server/properties.py`)

There is exactly **one** correct rendering of a drawer. It is Emacs's own:
`org-property-format` defaults to `"%-10s %s"` — key (colons included) padded
to ten characters, then one space, then the value — with a three-space body
indent. `:PROPERTIES:` and `:END:` stay at column zero.

```org
:PROPERTIES:
   :ID:       C5045326-9DC8-4F1E-A895-8895720DD928
   :CUSTOM_ID: project-asimap
   :CREATED:  <2026-04-03 Fri 23:13>
:END:
```

`:CUSTOM_ID:` is eleven characters, so it overflows its field by one — that is
correct, not a bug. Properties are ordered by `PROPERTY_ORDER`, then any
unknown ones alphabetically.

Choosing Emacs's format matters beyond taste: `org-set-property` writes drawers
we already consider canonical, so hand-editing in Emacs does not reintroduce
churn on the next write.

`normalize_drawers()` runs inside `write_file()`, so every file the server
writes gets canonical drawers regardless of which code path produced them —
including project files, which build their own drawers. It is **idempotent**:
already-canonical text comes back byte-identical, which means no diff, no
commit, and no churn. Drawers inside `#+begin_.../#+end_...` blocks are left
alone; so are unterminated drawers and ones containing unrecognised lines.

`heading_to_org_string()` uses the same `format_drawer()`, so what `get_task`
returns is byte-identical to what is on disk and a read-modify-write cycle
converges. The headline matters as much as the drawer here: it is rebuilt as
`STARS TODO [#PRIORITY] title [cookie] :tags:`, and orgmunge parses the
priority and progress cookie out of the title into separate attributes, so
rebuilding from the title alone silently deleted both on every write. Note
neither attribute is a plain string — an absent priority is still truthy and
only renders empty, so tests must be on the rendered text. The first write
after a read does legitimately differ, because it stamps `:MODIFIED:`; every
cycle after that is a fixed point. Regression tests are in
`tests/test_heading_roundtrip.py`.

**Known gap**: orgmunge also drops blank lines between sections on every
write, so whole-file round trips are still not byte-stable. That is tracked
separately and drawer formatting cannot fix it.

### Position Is Priority (`mcp_server/tasks.py`)

The top of the active section is what to work on next. A task that is never
picked up drifts down until its position is itself the signal that it no longer
matters. That makes file order load-bearing data, not presentation.

Every path that files a task goes through `place_child()`, never `add_child()`
directly. All three entry points used to append — to the *bottom*, which is
where passed-over work accumulates:

| operation | was | now |
|---|---|---|
| `create_task` | bottom | top |
| `move_task` | bottom | top of target |
| `update_task` (section change, either way) | bottom | top |
| `update_task` (same section) | preserved | preserved |

Reopening a `DONE` task is a strong signal it matters, and it used to be
buried. Finishing one now puts it at the top of Completed, so that list reads
newest-first. A same-section edit still preserves position: editing a task says
nothing about its priority and must not quietly promote it.

`position` is `top` / `bottom` / `before` / `after`, with `relative_to` naming
the anchor for the last two. **Not integer indices** — an index shifts every
time anything moves, so a caller would have to recompute one per call.
`before`/`after` express *ordering only*: a task placed after another is
follow-on work, not work blocked by it, and may proceed while the other is
still open. Do not model it as a dependency.

`reorder_task()` is a pure permutation, so it enforces a stricter check than
the general write guard: the section must hold exactly the same tasks
afterwards. It performs no ediff approval, because nothing about the task
changes — only its position, which is what was asked for.

`resort_completed_tasks()` is deliberately **not** automatic. New completions
already go to the top; this exists to close the seam above tasks completed
before that was true, and to be run on request. Undated tasks sort last in
their existing order rather than being given an invented date.

### Bounded Read Surface (`mcp_server/results.py`)

Every list and search tool renders through one envelope, so there is a single
convention to learn: `detail`, `limit`, `offset`, and a response that states
how to fetch the next page.

| level | returns | default page |
|-------|---------|--------------|
| `index` | one line per record | 50 |
| `snippet` | that line plus matching lines, ±1 context | 10 |
| `full` | the whole record | 3 |

Each level costs roughly 5× the lines of the one below, so the default page
shrinks to match and a response stays about the same size whichever level was
asked for. Naming a `limit` overrides this. `snippet` is the default for
search — an index line says *which* record matched but never *why*, so search
would otherwise always cost a second, blind fetch.

Every line carries a size hint (`[47L 1.2k]`) because record sizes are skewed
— journal entries run p50 = 11 lines, max = 927 — so a full read is usually
cheap and occasionally catastrophic, and the caller should be able to tell
which before asking.

`render()` takes **`warnings` as an explicit slot**, not something callers
append. The report of tasks the parser cannot see is a data-loss guarantee,
and anything appended below a result body can be paged past. It is emitted
above the results on every page, including an empty one — which is precisely
when it matters, since the tasks may be missing rather than absent.

Three contract decisions: `snippet` without a query degrades to `index` rather
than erroring, so a parameter's validity does not depend on which tool it was
passed to; an offset past the end says so and gives the total, since an empty
page is otherwise indistinguishable from no matches; `Record` splits into
prefix/title/suffix so a long line is trimmed at the title and never at the
reference a follow-up call needs.

`results.py` imports nothing from `tasks`, `journal` or `projects` — adapters
live in those modules, so the envelope stays free of the record types.

**A tool description is part of the API contract.** `list_tasks` once
advertised "Returns … full content" while returning one line per task, and an
agent used shell commands rather than pay for a call it believed was
expensive. `tests/test_read_surface.py` pins the *claim* — records carry long
bodies and each listing must stay inside a per-record line budget — because
asserting on wording is keyword whack-a-mole.

### Git Versioning (`mcp_server/versioning.py`)

Every org write is committed to that file's own git repository, so history is a
record of what changed and when. This is what turns a bad write from an
incident into a `git revert`.

Rules, in priority order:

1. **Versioning never breaks an org operation.** By the time it runs the file is
   already written. Not a repo, no git, a held `index.lock`, a rebase in
   progress — all logged and shrugged off.
2. **Only the touched file is committed.** Uses `repo.git.commit(... "--", path)`
   — a pathspec commit — *not* `repo.index.commit()`, which would sweep up
   whatever the user happened to have staged.
3. **We never create a repository.** No repo means no-op.

Because a pathspec commit takes the file's working-tree content, edits made
outside the server are swept into the next commit. That is intentional: no
version goes unrecorded, even when the server did not make the change.

Hooked into `write_file()` so no CRUD path can forget it; callers opt in by
passing a `summary`, which becomes `emacs-org-mcp: <summary>`. Backups are
added to the repo's `.gitignore` — they sit next to the file they protect,
which in a synced org directory would otherwise replicate everywhere.

### Ediff Approval (Enabled by Default)

By default, create/update operations present changes in Emacs ediff before applying them:
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
- To disable: Set `EMACS_EDIFF_APPROVAL=false` or use `--no-ediff-approval` flag

### MCP Resources for Documentation

The server provides comprehensive documentation via MCP resources, eliminating the need for extensive CLAUDE.md instructions:

**Resource Structure:**
- `emacs-org://guide/task-format` - Task format specification
- `emacs-org://guide/journal-format` - Journal format specification
- `emacs-org://guide/project-format` - Project format specification

**Implementation:**
- Guide content stored in `resources/guides/*.md` markdown files
- Loaded via `load_guide()` helper function at runtime
- Accessible to Claude via MCP resource protocol
- Keeps server.py focused on logic, not documentation

**Benefits:**
- Users need minimal CLAUDE.md configuration
- Documentation stays in sync with server version
- Easier to maintain and update
- More discoverable through MCP resource listing

## File Locations

| File | Path | Description |
|------|------|-------------|
| Tasks | `~/org/tasks.org` | Task list with Tasks/Completed Tasks sections |
| Journal | `~/org/journal/YYYYMMDD` | Daily journal files (with or without `.org` extension) |
| Projects | `~/org/projects/<slug>.org` | Individual project files |
| Project Index | `~/org/projects/index.org` | Auto-generated project index (do not edit) |

## Configuration

All settings can be overridden via environment variables or command-line flags:

| Variable/Flag | Default | Description |
|----------|---------|-------------|
| `ORG_DIR` / `--org-dir` | `~/org` | Base org directory |
| `JOURNAL_DIR` / `--journal-dir` | `$ORG_DIR/journal` | Journal files directory |
| `PROJECTS_DIR` / `--projects-dir` | `$ORG_DIR/projects` | Project files directory |
| `ACTIVE_SECTION` / `--active-section` | `Tasks` | Section name for active/TODO tasks |
| `COMPLETED_SECTION` / `--completed-section` | `Completed Tasks` | Section name for completed/DONE tasks |
| `HIGH_LEVEL_SECTION` / `--high-level-section` | `High Level Tasks (in order)` | Section name for the high-level task checklist |
| `EMACS_EDIFF_APPROVAL` / `--ediff-approval` / `--no-ediff-approval` | `true` | Visual approval via Emacs ediff (enabled by default, use `false` or `--no-ediff-approval` to disable) |
| `GIT_AUTOCOMMIT` / `--git-autocommit` / `--no-git-autocommit` | `true` | Commit each org file change to git (no-op if the org directory is not a repo) |
| `EMACSCLIENT_PATH` / `--emacsclient-path` | _(searches PATH)_ | Custom path to `emacsclient` executable (optional) |

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
| `reorder_task` | Move a task within its section (position = priority) |
| `resort_completed_tasks` | One-off: sort completed newest-first by `:CLOSED:` |
| `search_tasks` | Search tasks by query |

### Journal Tools

| Tool | Description |
|------|-------------|
| `list_journal_entries` | List entries for a date |
| `get_journal_entry` | Get entry by time or headline |
| `create_journal_entry` | Create new entry |
| `update_journal_entry` | Update existing entry |
| `search_journal` | Search entries across recent days |
| `list_journal_dates` | List which dates have entries, with counts and sizes |

### Project Tools

| Tool | Description |
|------|-------------|
| `list_projects` | List all projects, optionally filtered by status |
| `get_project` | Get project by slug, CUSTOM_ID, or title substring |
| `create_project` | Create new project file from org-formatted string |
| `update_project` | Update project section, properties, headline, or tags |
| `search_projects` | Search across all projects |
| `link_task_to_project` | Add a task link to a project's Related Tasks section |

## Code Style

- Use `match/case` statements instead of `if/elif/else` chains
- Type hints throughout (Python 3.13+ syntax: `list[str]`, `str | None`)
- Dataclasses for structured data (`Task`, `JournalEntry`, `Project`)
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

- No support for org-mode priorities (`[#A]`, `[#B]`, `[#C]`) or progress
  cookies (`[1/3]`, `[50%]`) as *queryable* fields — they are not parsed into
  `Task`, but they do survive a read-modify-write cycle unchanged
- No support for scheduled/deadline timestamps in parsing (preserved in content)
- Journal files use manual parsing, not orgmunge
- No concurrent access protection (relies on single-user access pattern)
- orgmunge does not honour `#+begin_src`/`#+begin_example` fencing; the server
  works around it by comma-escaping heading-like lines inside blocks on write,
  but org content written to these files by other means can still confuse the
  parser (`find_unparsed_tasks()` will report it)
- Replacing orgmunge with a purpose-built line-oriented module is the standing
  plan. The case for it is the accumulated behaviour, not a single defect: the
  renderer drops blank lines between sections (so whole-file round trips are not
  byte-stable, and no drawer formatting can fix that), `#+begin_src` fencing is
  not honoured, only the first `**` heading of a parsed fragment is kept, and
  the drawer token needed patching outright. The dependency surface is small and
  confined to `tasks.py` — `Org(path)`, `root.children`,
  `headline.{title,level,todo,tags}`, `properties`, `body`, `children`,
  `add_child`, `remove_child`, `str(org)` — and much of the raw-text scanning a
  replacement needs already exists (`scan_task_identities`,
  `scan_section_headings`, `normalize_drawers`, `find_indented_headings`,
  `escape_headings_in_blocks`). Note the DOTALL problem is *not* systemic across
  the lexer: `t_DRAWER` is its only pattern with unbounded newline reach.

## Related Files

- `~/.claude/CLAUDE.md` - Main Claude instructions including task/journal format specs
- `~/org/tasks.org` - The actual tasks file
- `~/org/journal/` - Journal directory

## Dependencies

From `pyproject.toml`:
- `mcp>=1.0.0` - MCP SDK for server implementation
- `orgmunge>=0.3.1` - Org-mode AST manipulation

The `orgparse` dependency in pyproject.toml is not currently used and can be removed.
