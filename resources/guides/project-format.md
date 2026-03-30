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

### Tasks to Projects

Add a `:PROJECT:` property to the task's `:PROPERTIES:` drawer:

```org
** TODO GH-28 Implement feature
:PROPERTIES:
   :CUSTOM_ID: task-gh-28
   :PROJECT:  project-booklore
:END:
```

The value is the project's `:CUSTOM_ID:`.

### Projects to Tasks

Add org-mode file links in the `Related Tasks` section:

```org
** Related Tasks
- [[file:~/org/tasks.org::#task-gh-28][GH-28 Implement feature]]
- [[file:~/org/tasks.org::#task-gh-42][GH-42 Write documentation]]
```

Use the `link_task_to_project` tool to add these links.

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
