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
├── emacs_archive.el       # Emacs Lisp that drives org-archive-subtree
├── manual_test_ediff.py   # Manual test script for ediff approval
├── manual_test_archive.py # Manual test script for archiving via Emacs
├── mcp_server/            # Server implementation
│   ├── archiving.py       # Archive a task out of tasks.org, by way of Emacs
│   ├── config.py          # Config dataclass and global state
│   ├── corpus.py          # Cross-scope search_org over all four corpora
│   ├── tools.py           # MCP tool definitions and dispatch
│   ├── resources.py       # MCP resource definitions and guide loading
│   ├── tasks.py           # Task CRUD, orgmunge ops, write guard
│   ├── files.py           # Loose org files as a searchable corpus
│   ├── journal.py         # Journal CRUD (manual parsing)
│   ├── orgmunge_patch.py  # Line-oriented fix for orgmunge's drawer lexer
│   ├── projects.py        # Project CRUD (manual parsing)
│   ├── properties.py      # Canonical :PROPERTIES: drawer format
│   ├── results.py         # Shared result envelope: detail levels, paging
│   ├── search.py          # BM25 ranking, tokenising, orderings
│   ├── validation.py      # Heading-level validation, block escaping
│   ├── versioning.py      # Git auto-commit of org file changes
│   └── utils.py           # Timestamps, atomic file I/O, Emacs bridge
├── resources/guides/      # MCP resource guide files
│   ├── task-format.md
│   ├── journal-format.md
│   └── project-format.md
└── tests/
    ├── conftest.py        # Shared fixtures and factories
    ├── test_archiving.py
    ├── test_config.py
    ├── test_ediff.py
    ├── test_factories.py
    ├── test_journal.py
    ├── test_projects.py
    ├── test_properties.py
    ├── test_corpus_search.py    # Loose files and cross-scope search
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

### Every Org File Is Searchable (`mcp_server/files.py`, `mcp_server/corpus.py`)

The typed tools encode a set of conventions — a `tasks.org` with named
sections, dated journal files, one file per project. Every other org file in the
directory was unreachable by all of them: archived work, dated design notes, a
scratch file of half-finished thinking. That is precisely the long-tail material
open-ended recall is for, and the material least likely to have been filed under
a convention in the first place.

`search_org(query, scope)` unions the four corpora into **one** ranking rather
than searching each and merging. IDF is a property of the corpus being scored,
so ranking each scope apart makes the same term worth different amounts in one
result set — the scores become incomparable exactly where they must be
compared. Every result line names its scope, because the follow-up call differs
(`get_task` / `get_journal_entry` / `get_project` / open the org link).

**A record is a heading plus its own body, not its subtree.** Subtree records
count every deep term again in each ancestor, and BM25 over overlapping
documents ranks the outermost heading above the one that answers the query. It
follows that a heading holding nothing but more headings is not a record — its
text lives in its children, and it would match on its title and return nothing
to read. Ancestors survive as the path shown on the result line.

Three shapes in the real corpus decide the rest of the parsing, and each breaks
a different naive split: a file with **no headings at all** (the file is the
record), a file opening with **text above its first heading** (that text belongs
to the file), and a file that **never uses level one** (a parent is found by
level, not by being the previous heading). Heading-like lines inside
`#+begin_src` blocks are not headings — org disagrees, which is what
`escape_headings_in_blocks()` repairs on write, but on read the author's meaning
is what a search should return, and a file this server did not write may never
have been through that repair.

**The file's name is indexed with every record it holds.** A file named
`2024.03.11-queue-migration-design.org` states its subject where its headings
only cover the parts.

**Ownership is by rule, not by directory.** `owned_by_typed_corpus()` skips
`tasks.org` exactly, journal files matching `JOURNAL_FILENAME_RE`, and
`projects/*.org` — which is what keeps `tasks.org_archive` searchable while
`tasks.org` is not counted twice. The predicate applies whatever the scope, so
`files` means the same set every time rather than depending on what it was asked
for alongside. `projects/index.org` is owned and therefore skipped: it is
derived, and a hit in it returns a table of contents where the project is the
answer.

Splitting this finely does surface generic subsection headings
(`Description`, `Task items`) as records of their own. Measured over recall
queries, they stay in the low single digits per page and never rank first, and
the heading path on the result line says which record each belongs to — so
merging them into their parent would cost more than it saves.

Archive files are handled as a **convention** (`<name>_archive`), not a named
file, so it works for whatever files an installation has. Hits from one are
marked `[archived]`, since that work is finished or abandoned and it describes
what was done rather than what the code does now.

`files.py` imports nothing from `tasks`, `journal` or `projects` — the skip
predicate is passed in — so the files scope is testable in a bare directory,
which is the installation it exists for.

### Timestamps Are Comparable (`mcp_server/search.py`)

`SearchDoc.sort_key` is normalised on construction, so a provider hands over
whatever timestamp it holds and cannot get the comparison wrong.

It was getting it wrong. Four shapes were being sorted as raw strings — an
org active timestamp `<...>`, an inactive one `[...]`, a journal's
`YYYYMMDD HH:MM`, and nothing at all — and `<` sorts before `[`. So
`order="recent"` grouped by **bracket**: every undated task first, then every
never-modified one (which carries `<CREATED>`), then every modified one (which
carries `[MODIFIED]`) — each group correctly dated and the groups in the wrong
order. A task edited today sorted below one created years ago and never touched.
Cross-scope search would have compounded it, since the journal's shape sorts
before both.

A record carrying no date sorts **last in both directions** — neither end of a
chronology is where an unknown date belongs. This follows what
`resort_completed_tasks()` already does rather than inventing a date.

### Linking Is Mechanical (`mcp_server/linking.py`)

A link carries no judgement. Once someone has decided a task belongs to a
project, the link is one known-shaped line in a known section and one property
in a drawer — so there is **no ediff approval**. That is the rule generally:
approval is for content a person might want to edit before it lands, not for
structural changes they have already asked for. `reorder_task` skips it for the
same reason.

**Both ends, in one call.** The task carries `:PROJECT:` and the project lists
the task. Leaving either to the caller is how they drift, which the live data
showed: `:PROJECT:` held two different spellings because nothing owned the
field.

**Not atomic, and idempotent instead.** Two files means a failure between
writes leaves one end done. Both ends are validated and both contents computed
before anything is written, but the real guarantee is that re-running completes
whichever end is missing — better than a claim of atomicity that cannot hold
across two files.

**Idempotency is judged on the link, not the text.** The project end matches
the `#task-id` anchor, not the rendered line, because a headline changes over a
task's life and a text comparison would append a second link after any rename.
The task end accepts any `:PROJECT:` resolving to the same project and rewrites
it to canonical form, so an unsanctioned value is repaired by ordinary use.

A task belongs to one project: linking one already linked elsewhere is refused
rather than silently repointed, which would leave the first project pointing at
a task that no longer claims it.

The project index is a derived artifact rebuilt from a directory scan. It is
refreshed after a link and a failure there is logged, not raised — a healthy
link must not report as broken because a derived file could not be rebuilt.

### Every Task Has an Id (`mcp_server/tasks.py`)

`:CUSTOM_ID:` is what everything else addresses a task by — a project links to
it, a `Record` hands it back as the reference for the next call, and archiving
needs it as a locator because `find_task` resolves a substring to its *first*
match, which is right for reading a task and wrong for a write that removes
one.

So it is an **invariant**, not a precondition of one operation. It used to be
three different answers to the same question:

| site | was | now |
|---|---|---|
| `create_task` | minted `:ID:` and `:CREATED:`, not `:CUSTOM_ID:` | mints all three |
| `link_task_to_project` | refused: "Give it one first" | mints, then links |
| `archive_tasks` | minted | mints (unchanged) |
| `update_task` | preserved an existing one | unchanged, already right |

The helpers live in `tasks.py` because that is the only home that avoids a
cycle: minting needs `scan_task_identities` and `extract_task_description`, and
`create_task` is there. `archiving.py` and `linking.py` import them, and
`tasks.py` imports `archived_ids` from `files.py`, which depends on neither.

**`create_task` prevents; `ensure_custom_id` repairs.** Minting at creation is
what makes it an invariant; the repair path exists for tasks written before it
and for anything arriving by other means. The repair writes through the
ordinary guarded path and commits on its own, *before* the operation that asked
for it — so a caller that then fails leaves a property addition explained by its
own commit. It also passes the task's raw `headline:<text>` identity as the
guard's `target`, because giving a task an id changes the identity the guard
knows it by.

**A ticket is not an id.** One ticket routinely covers several tasks, so
`task-srt-1878` would collide meaningfully and the numeric suffix would say
nothing about which task it is. Tickets are therefore *dropped* from the slug,
not promoted to it. Org links are reduced to their description first: a headline
carrying its ticket as a link otherwise slugs the URL —
`[[https://host/browse/ABC-1][ABC-1]] Fix the thing` minted
`task-https-host-browse` before this, which is not a truncation problem but a
parsing one.

**The shape rule is enforced wherever an id is used, not only where it is
minted**, because an id can arrive by hand. `CUSTOM_ID_RE` allows letters,
digits, dots, dashes and underscores — narrower than org, because the value goes
into a link anchor as `::#<id>`, where a colon makes a link org may read
differently, and archiving interpolates it into elisp source, where an
unescaped quote is not a bad argument but different code.

**Uniqueness spans the files an id can travel to.** `mint_custom_id` checks
`tasks.org` *and* the archives, so a minted id cannot collide with a task that
left the file last year. It reads the archives itself rather than taking them
from the caller: an id source a caller has to remember to supply is one a new
mint site is written without, and the two sites added by this change —
`create_task` and `link_task_to_project` — are exactly the ones that would have
forgotten. `load_archives()` and `archived_ids()` therefore live in `files.py`,
which already owns the `<name>_archive` convention and which `tasks.py` can
import without a cycle.

**The tasks that already have none are left alone.** They get an id the first
time they are linked or archived. A bulk rewrite would touch tasks nobody asked
about, and every one of those writes is a commit.

### Archiving Is Org's Job (`mcp_server/archiving.py`, `emacs_archive.el`)

Org already knows how to archive a subtree — which file receives it, what
context to record with it, what level it arrives at. So Emacs does the move,
`org-archive-subtree` over `emacsclient`, and the server owns everything
around it. The elisp is one function: widen, find the heading by
`:CUSTOM_ID:`, archive, save both buffers, return the resolved archive path.
Anything else is an `error`, which reaches Python as exit 1 with the message.

**This is the one write that legitimately removes a task**, which is precisely
what `write_tasks_org`'s guard refuses. It cannot use that path, so every
guarantee that path provides is rebuilt here:

| guarantee | how |
|---|---|
| nothing else vanished | `verify_archive()` — raw-text scans, per task |
| recoverable | `backup_file()` pre-image, taken before Emacs is invoked |
| recorded in git | `commit_file()` on tasks.org and on the archive |

**Keyed on `:CUSTOM_ID:`.** `find_task` resolves a substring to its *first*
match — right for reading a task, wrong for removing one. A task with no id
gets one first, via `ensure_custom_id` (see "Every Task Has an Id"), committed
on its own before Emacs is invoked; archiving passes the ids its archives hold
so the minted one cannot collide with something already archived. The id is
quoted with `quote_elisp` on its way into elisp source, where an unescaped
quote is not a bad argument but different code.

**Prefer a duplicate to a hole.** On a verification failure tasks.org is
restored from the pre-image — through `write_file()`, so the rollback is a
commit like any other write — and the archived copy is left where org put it.
A task in two places is recoverable by hand; a task in neither is not. The
report names the pre-image and says to revert the tasks.org buffer, which
Emacs is still holding.

**The archive location is read from Emacs, never assumed.**
`org-archive-location` is overridable globally, per-file with `#+ARCHIVE:`,
and per-subtree with an `:ARCHIVE:` property, so the elisp reports what
`org-archive--compute-location` resolved at point. Two of org's answers change
what happens next and are reported: a location outside `SEARCH_ROOTS` is
unreachable by `search_org`, and one not named `<name>_archive` will not be
marked `[archived]`.

**Emacs is asked before anything is written.** Archiving may have to write
a `:CUSTOM_ID:` first, and a file whose buffer holds unsaved edits must not be
written at all — so `ensure_emacs_ready()` puts the buffer question up front
rather than letting it surface when the archive itself is refused. Asking
afterwards left a property addition, and its commit, for a task that never
moved, in a file whose buffer would clobber it on the user's next save. The
archive checks again when it runs: the calls are seconds apart, but the buffer
belongs to somebody who is typing in it.

**Resolution is all-or-nothing; archiving is one at a time.** An identifier
matching nothing or matching two refuses the whole call and names the
candidates — what the user confirmed was a list, and archiving the subset that
happened to resolve is not that list. The run then stops at the first failure,
since whatever stopped one task will stop the next.

**Both ends, as with linking.** The project's `Related Tasks` line has its
path rewritten to the archive, keeping the `::#task-id` anchor that
`linking.py` judges an existing link by, so the project keeps its record of
work that happened. `:PROJECT:` travels into the archive inside the drawer.
The `High Level Tasks` line is removed *after* the archive verifies — before
would mean a failed archive deleting a live task's tracking line — and
reported as `removed` or `not found`, since the description match is fuzzy
enough to no-op.

That removal is why `remove_high_level_task()` takes **text** where its `add`
and `update` siblings take an `Org`: those run inside `create_task` and
`update_task`, which are already rewriting the file through orgmunge, whereas
Emacs has just written this file with its blank lines intact. Rendering the
whole file through the parser to delete one line would collapse every blank
line between sections, turning a move into a diff over everything.

**No ediff, and no `confirmed` parameter.** Mechanical, like linking and
`reorder_task`: nothing here is generated prose a person might want to edit
first. What archiving needs is *direction*, and a flag the caller sets itself
proves nothing — so the protocol (user named them / user described a class,
so list and ask / you think they are stale, so suggest and wait) lives in the
tool description and the task guide, which is what an agent reads before
calling.

**Emacs absent is a hard failure**, the deliberate opposite of
`request_ediff_approval`'s shrug: falling back there means skipping a review,
here it would mean nothing does the work. It is not gated on
`EMACS_EDIFF_APPROVAL`, which configures an approval UI rather than whether
Emacs is reachable.

`run_org_archive()` is the seam. `tests/test_archiving.py` replaces it with a
fake that *really* moves the heading between files, since verification reads
the files rather than the report; `manual_test_archive.py` covers the elisp
against a live Emacs in a throwaway org directory.

### Every Org Path Follows `org_dir` (`mcp_server/config.py`)

`journal_dir` and `projects_dir` are derived from `org_dir` in
`Config.__post_init__`, not by whoever builds the Config.

They used to carry their own defaults pointing at the real org directory, with
only `load_config` repairing them. That made the server correct and every
*direct* construction wrong: a `Config(org_dir=<temp>)` read its tasks from the
temp directory — `tasks_file` was the one derived path — while writing projects
and journal entries to the user's live files. It is not a hypothetical; it
wrote 11 links into a real project file.

`tests/conftest.py` deliberately passes **only** `org_dir`. It used to name all
three, which is what kept 300+ tests from noticing. Leaving the subdirectories
to be derived means any regression writes to the real org directory during a
test run, so the whole suite guards this rather than one test.

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
| `ORG_DIR` / `--org-dir` | `~/org` | Base org directory. The journal and projects directories derive from it unless set explicitly |
| `JOURNAL_DIR` / `--journal-dir` | `$ORG_DIR/journal` | Journal files directory |
| `PROJECTS_DIR` / `--projects-dir` | `$ORG_DIR/projects` | Project files directory |
| `SEARCH_ROOTS` / `--search-root` | `$ORG_DIR` | Directories walked for loose org files. The variable takes several separated like `PATH`; the flag is repeatable |
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
| `archive_tasks` | Archive tasks out of tasks.org via org's `org-archive-subtree` |
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
| `link_task_to_project` | Link a task and a project, both ends, no ediff |
| `unlink_task_from_project` | Remove the link, both ends |

### Cross-Scope Tools

| Tool | Description |
|------|-------------|
| `search_org` | Search tasks, journal, projects and loose org files as one ranked set |

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
- Loose org files are searchable but not writable: `search_org` reads them,
  and no tool edits one. `archive_tasks` writes into an `_archive` file only
  by way of org itself; nothing unarchives a task
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
