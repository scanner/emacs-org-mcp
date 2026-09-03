# Repairing task↔project link drift

A runbook for bringing an org directory's task↔project links back into the
shared format. Written to be handed to an agent session on any host.

## What drifts, and why

`:PROJECT:` must hold the project's `:CUSTOM_ID:` — the `project-<slug>` form —
and every task naming a project must also appear in that project's
`Related Tasks` section. Those are the two ends of one link.

Before `link_task_to_project` maintained both ends, the two halves were separate
calls and the property was written by hand. So installations that predate it
accumulate two kinds of drift:

- **Non-canonical values.** `:PROJECT: my-project` instead of
  `:PROJECT: project-my-project`. On the machine this runbook was written from,
  9 of 23 tasks held the bare slug.
- **Half-links.** The task names the project but the project does not list the
  task, or the reverse.

The guides always specified the canonical form. It drifted anyway, because
applying it was manual across sessions, hosts and months. That is the reason
this is a repair procedure and not a documentation fix.

## Prerequisites

The server must have `link_task_to_project(task_identifier,
project_identifier)`. If that tool takes a `task_link` string instead, it
predates this work — stop and report it rather than repairing by hand.

## 1. Safety gate

```
mcp: list_tasks(section="Tasks", limit=1)
```

If the output carries a WARNING about tasks or sections the parser cannot see,
**stop and report it.** That is a data-loss condition; it needs a human before
anything writes. The write guards will refuse to lose a task, but the situation
itself is not something to repair around.

Record a baseline to check against at the end:

```bash
cd ~/org && git status --short   # must be clean; if not, stop and ask
echo "tasks:    $(grep -cE '^\*\* (TODO|DONE|NEXT|WAIT|BLOCK|CNCL) ' tasks.org)"
echo "sections: $(grep -c '^\* ' tasks.org)"
echo "cookies:  $(grep -cE '^\*\*\* Task items \[[0-9]' tasks.org)"
```

If `~/org` is not a git repository, take a copy of `tasks.org` and `projects/`
instead. Every step below is reversible only if there is something to revert to.

## 2. Census — parse, do not grep windows

Pair each task with its `:PROJECT:` using a state machine over the file:

```bash
cd ~/org && awk '
  /^\*\* (TODO|DONE|NEXT|WAIT|BLOCK|CNCL) /{id=""; proj=""}
  /^ *:CUSTOM_ID:/{id=$2}
  /^ *:PROJECT:/{proj=$2; if(id) print proj"\t"id}
' tasks.org | sort > /tmp/pairs.tsv

# Sanity check: every :PROJECT: line must have been paired with a task.
echo "paired: $(wc -l < /tmp/pairs.tsv)  raw: $(grep -c '^ *:PROJECT:' tasks.org)"

# Which values are in use. Anything not starting "project-" is non-canonical.
cut -f1 /tmp/pairs.tsv | sort | uniq -c
```

If `paired` and `raw` disagree, the pairing missed something. Investigate before
writing anything.

**Do not use `grep -B4 :PROJECT:` to find the nearby `:CUSTOM_ID:`.** Drawers
vary in length, so a fixed window misaligns ids and gives a confidently wrong
answer. That mistake produced three different wrong counts during the original
repair before it was caught.

## 3. Find orphans — tasks whose heading is gone

A `:PROPERTIES:` drawer can survive while its `** TODO` heading is lost,
absorbed into the previous task's body. `find_unparsed_tasks()` cannot see
these: it scans for `**` headings, and there is none to find.

```bash
cd <path-to-emacs-org-mcp> && PYTHONPATH=. uv run python -c "
import re
from pathlib import Path
import mcp_server
from mcp_server.config import Config, global_state
from mcp_server.tasks import list_tasks
global_state.config = Config(org_dir=Path.home()/'org',
                             ediff_approval=False, git_autocommit=False)
raw = {m.group(1) for m in re.finditer(
    r'^ *:CUSTOM_ID: *(\S+)',
    (Path.home()/'org'/'tasks.org').read_text(), re.M)}
seen = {t.custom_id for s in ('Tasks','Completed Tasks') for t in list_tasks(s)}
print('orphans:', sorted(i for i in (raw - seen) if i))
"
```

Filtering falsy ids is load-bearing: a task with no `:CUSTOM_ID:` at all parses
to `''`, which would otherwise be reported as an orphan.

**Do not repair an orphan.** Its headline is unrecoverable unless something else
recorded it:

```bash
cd ~/org && git log --oneline -S "<the-custom-id>" -- tasks.org
```
```
mcp: search_journal(query="<the-custom-id>", days_back=0)
```

If neither has it, report the orphan and stop there. Choosing a headline is
inventing content for a task someone else wrote; leave it to them.

## 4. Repair

`link_task_to_project` is idempotent and reports each end separately, so you do
**not** need to work out which links are broken. Call it once for every
`(project, task)` pair from the census. Correct pairs report "already as asked"
and write nothing.

This matters: identifying the broken subset is exactly where the original repair
kept going wrong. A census that looked only for non-canonical values missed four
tasks that held the canonical value and were still missing their project end.

Pass the canonical project id as `project_identifier` where you have it; a
non-canonical `:PROJECT:` value still resolves, and the tool rewrites it.

For each line in `/tmp/pairs.tsv`, skipping any orphan:

```
mcp: link_task_to_project(task_identifier="<task-id>",
                          project_identifier="<project-slug-or-custom-id>")
```

Expect one of:

| task end | project end | meaning |
|---|---|---|
| `set` or `normalized` | `added` | both ends repaired |
| `already correct` | `added` | project end was missing |
| `normalized` | `already correct` | property was wrong only |
| `already correct` | `already correct` | nothing to do |

Two refusals are possible and neither should be forced:

- **"already linked to `<other>`"** — the task names a different project. A task
  belongs to one project, and silently repointing it would leave the other
  project's `Related Tasks` pointing at a task that no longer claims it. Report
  it; the human decides, and `unlink_task_from_project` is how they change it.
- **"Could not find task"** — an orphan missed in step 3.

## 5. Verify

```bash
cd ~/org

echo "tasks/sections/cookies, must match step 1:"
echo "  $(grep -cE '^\*\* (TODO|DONE|NEXT|WAIT|BLOCK|CNCL) ' tasks.org) / \
$(grep -c '^\* ' tasks.org) / $(grep -cE '^\*\*\* Task items \[[0-9]' tasks.org)"

echo "non-canonical values left (only an orphan is acceptable):"
awk '/^ *:PROJECT:/{if ($2 !~ /^project-/) print "  "$2}' tasks.org

echo "duplicate links:"
for f in projects/*.org; do
  d=$(grep -oE '#task-[a-z0-9-]+' "$f" | sort | uniq -d)
  [ -n "$d" ] && echo "  $f: $d"
done

echo "half-linked (task names a project but the project omits it):"
while IFS=$'\t' read -r proj id; do
  slug=${proj#project-}
  grep -q "#${id}\]" "projects/${slug}.org" 2>/dev/null \
    || echo "  $id -> $proj"
done < /tmp/pairs.tsv

git status --short   # expect clean: every write auto-commits
```

Task, section and cookie counts **must** be identical to step 1. If any moved,
stop and report. Each write is its own commit, so a revert is cheap and
targeted.

## 6. Report

State plainly:

- how many `:PROJECT:` values were normalised
- how many project-end links were added
- which tasks were refused, and why
- which orphans were found, and that they need a headline chosen

Say so directly if there was nothing to repair. On an installation that has only
ever used the current tool, that is the expected outcome.

## What this looked like the first time

For reference, on the machine this was written from — 165 tasks, one project:

| | before | after |
|---|---|---|
| non-canonical `:PROJECT:` | 9 | 1 (the orphan) |
| canonical `:PROJECT:` | 14 | 22 |
| `Related Tasks` links | 11 | 22 |
| tasks / sections / cookies | 165 / 2 / 142 | unchanged |

Twelve tasks were repaired: the 8 non-canonical values, plus 4 more that only
surfaced once those were fixed. One orphan remains, awaiting a headline.
