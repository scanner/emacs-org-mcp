# Project Format

## File Location

Projects live as individual `.org` files in `~/org/projects/` (configurable via `PROJECTS_DIR` or `--projects-dir`).

- Each project gets its own file: `~/org/projects/<slug>.org`
- An auto-maintained `index.org` provides an overview of all projects grouped by status
- Do not edit `index.org` manually — it is regenerated on every project create/update

## Structure

```org
* Project Title                                            :project:
:PROPERTIES:
   :ID:       <UUID>
   :CUSTOM_ID: project-<slug>
   :CREATED:  <2026-03-29 Sun 10:00>
   :MODIFIED: [2026-03-29 Sun 10:00]
   :STATUS:   active
   :REPO:     https://github.com/user/repo
:END:

** Description
What this project is and why it exists.

** Design
Architecture decisions, key constraints, technical approach.

** Goals [2/5]
- [X] Completed goal
- [ ] Pending goal
- [ ] Another goal

** Related Tasks
- [[file:~/org/tasks.org::#task-gh-28][GH-28 Task description]]
- [[file:~/org/tasks.org::#task-gh-42][GH-42 Another task]]

** Related Links
- [[https://github.com/user/repo][GitHub Repository]]
- [[https://github.com/user/repo/pulls][Open PRs]]

** Notes
Freeform notes, decisions, context.
```

## Heading Levels

**A project file is one `*` heading. Every section must be `**` or deeper.**

```org
* Project Title  :project:   <- one per file
** Description               <- correct
*** Sub-topic                <- correct
* Other Project              <- WRONG: only the first * heading is read
```

A second `*` heading makes everything after it unreachable. The server rejects
such entries and names the bad line. The same rule applies to `update_project`
section bodies: content under a `**` section must use `***` or deeper.

To quote org syntax, wrap it in `#+begin_example` — the server comma-escapes
the contents.

## Properties

All properties live in the `:PROPERTIES:` drawer immediately after the heading.

| Property | Required | Description |
|----------|----------|-------------|
| `:ID:` | Auto | UUID for org-mode compatibility. Auto-generated on create. |
| `:CUSTOM_ID:` | Yes | Stable identifier in `project-<slug>` format. Used for linking. |
| `:CREATED:` | Auto | Active timestamp `<>` set when project is created. |
| `:MODIFIED:` | Auto | Inactive timestamp `[]` updated on every modification. |
| `:STATUS:` | Yes | Project status (see values below). Defaults to `planning` on create. |
| `:REPO:` | No | Repository URL. Omitted if not applicable. |

**Note on timestamps**: All timestamps are naive (no timezone) as org-mode does not support timezone information.

## Status Values

| Status | Meaning |
|--------|---------|
| `active` | Currently being worked on |
| `planning` | In design/planning phase, not yet started |
| `on-hold` | Paused, may resume later |
| `completed` | Finished |

## Sections

All sections are level-2 headings (`**`) within the project file. The canonical sections are:

| Section | Purpose |
|---------|---------|
| `Description` | What the project is and why it exists |
| `Design` | Architecture decisions, technical approach, key constraints |
| `Goals` | Checklist of project-level milestones with `[/]` progress cookie |
| `Related Tasks` | Org-mode links to tasks in `tasks.org` |
| `Related Links` | External links (repo, PRs, docs, dashboards) |
| `Notes` | Freeform notes, context, decisions |

Not all sections are required. Use only what is relevant to the project. Additional custom sections may be added.

## Cross-Linking

Projects, tasks, and journal entries link to each other:

Linking a task and a project is **one call**, which maintains both ends.

### Tasks and Projects

`link_task_to_project` sets the task's `:PROJECT:` to the project's
`:CUSTOM_ID:` and adds the task to the project's `Related Tasks`:

```org
** TODO GH-28 Implement feature
:PROPERTIES:
   :CUSTOM_ID: task-gh-28
   :PROJECT:  project-booklore
:END:
```

```org
** Related Tasks
- [[file:~/org/tasks.org::#task-gh-28][GH-28 Implement feature]]
```

The link targets the task's `:CUSTOM_ID:` anchor, which is what makes it both
clickable in Emacs and findable by `search_tasks` — the anchor is a search
term, and the description stays readable.

Do **not** write either end by hand. The tool owns both, which is what keeps
`:PROJECT:` in one shape across every file.

`unlink_task_from_project` removes both ends. Both are idempotent and neither
asks for approval: a link is mechanical, so there is nothing to review.

A task may belong to one project. Linking a task already linked elsewhere is
refused rather than silently repointed.

### Required Workflow

- **Creating or updating a project**: `search_tasks` for tasks that belong to
  it, then `link_task_to_project` for each match.
- **Creating or updating a task**: `list_projects` for a matching project,
  then `link_task_to_project`. If none matches, do not link.

### Journal Entries for Projects

Session logs, progress updates, and implementation notes belong in journal entries, **not** in the project file. This keeps project files focused on structure and state rather than growing unboundedly with session history.

When creating a journal entry related to a project:
1. **Tag the entry** with the project slug (e.g., `:booklore:`)
2. **Link to the project file** in the entry body: `[[file:~/org/projects/booklore.org][Booklore]]`

Example:
```org
** 14:30 Booklore implement chunking pipeline :booklore:
- Implemented sliding window chunker with sentence boundary detection
- See [[file:~/org/projects/booklore.org][Booklore]] project for design context
```

## Finding Projects

The `get_project` tool accepts any of:
- **Slug**: `booklore`
- **CUSTOM_ID**: `project-booklore`
- **Title substring**: `Booklore` (case-insensitive)

## Updating Projects

The `update_project` tool supports **section-level updates** to avoid rewriting the entire file. This is important for large projects.

### Update a section
Provide `section` (name) and `content` (new body):
```json
{"identifier": "booklore", "section": "Goals", "content": "- [X] Chunking\n- [ ] Embedding"}
```

### Update properties
Provide `properties` as a dict:
```json
{"identifier": "booklore", "properties": {"STATUS": "active", "REPO": "https://..."}}
```

### Update headline or tags
```json
{"identifier": "booklore", "headline": "Booklore: Fiction RAG", "tags": ["project", "ai"]}
```

Multiple update types can be combined in a single call. The `:MODIFIED:` timestamp is always updated automatically.

## Creating Projects

Use `create_project` with a complete org-formatted string. The server will:
- Auto-generate `:ID:` (UUID) if not provided
- Set `:CREATED:` timestamp
- Default `:STATUS:` to `planning` if not provided
- Add `:project:` tag if not present
- Derive the slug from `:CUSTOM_ID:` (stripping `project-` prefix)

Always check for existing projects before creating to avoid duplicates.
