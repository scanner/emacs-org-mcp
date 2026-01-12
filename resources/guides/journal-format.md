# Journal Format Guide for emacs-org MCP

## Overview

Journal entries are stored in `~/org/journal/` (or configured directory) with daily files named `YYYYMMDD` (no extension, e.g., `20250115`).

## File Structure

```org
* YYYY-MM-DD

** HH:MM Entry headline :tags:
- Bullet point detail
- Another detail

** HH:MM GH-28 [[https://github.com/org/repo/pull/28][#28]] Work description
- Specific accomplishment
- Another accomplishment

** HH:MM Daily summary :daily_summary:
- Overview of the day's work
- Key decisions made
```

## Entry Format

**Format:** `** HH:MM [TICKET-ID] headline :tags:`

### Components:

1. **Time:** `HH:MM` in 24-hour format (e.g., `14:30`, `09:15`)
2. **Ticket ID (optional):** `GH-123` for GitHub issues
3. **PR Link (optional):** `[[URL][#PR-NUMBER]]` inline after ticket ID
4. **Headline:** Concise summary of the entry
5. **Tags (optional):** `:tag1:tag2:` at the end (e.g., `:daily_summary:`)

### Content:

- Use bullet points (`- `) for entry details
- Keep bullets concise and specific
- Focus on what was accomplished, not just activities
- Include key decisions and blockers/follow-ups

## Common Tags

- `:daily_summary:` - End-of-day summary entry
- `:meeting:` - Meeting notes
- `:blocked:` - Work that's blocked
- `:decision:` - Important technical decision

## GitHub Integration

### Issues

Format issue IDs as `GH-<number>` in the headline:
```org
** 14:30 GH-127 Implemented authentication
```

### Pull Requests

Include PR links inline after the issue ID:
```org
** 14:30 GH-127 [[https://github.com/org/repo/pull/221][#221]] Submitted PR
```

Use `gh pr view --json` to gather PR info when creating PR-related entries.

## Linking Between Journal and Tasks

**Link to tasks from journal entries:**
```org
** 14:30 Work on authentication feature
- Made progress on [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2 task]]
- Completed two subtasks
- Next: Add unit tests
```

**Multiple task links:**
```org
** 16:00 Code review and bug fixes
- Reviewed [[file:~/org/tasks.org::#task-gh-125][GH-125 API refactor]]
- Fixed bugs in [[file:~/org/tasks.org::#task-gh-130][GH-130 user validation]]
- Both ready for merge
```

**Multiple PR links:**
```org
** 17:00 Submitted PRs for review
- [[https://github.com/org/repo/pull/221][#221]] OAuth2 implementation
- [[https://github.com/org/repo/pull/222][#222]] Fix validation errors
- Both passing CI checks
```

**Link format:** `[[file:~/org/tasks.org::#CUSTOM_ID][Display Text]]`

This creates clickable links that navigate directly to the referenced tasks.

## When to Create Entries

1. **On explicit request:** User says "log this", "add to journal", etc.
2. **End of session:** User says "we're done", "wrap up" - create `:daily_summary:` entry
3. **Significant milestones:** Suggest (don't auto-create) for major accomplishments

## Entry Guidelines

### DO:
- Keep headline concise (1 line)
- Use bullets for specific details
- Batch related work into single entry
- Include key decisions and outcomes
- Note blockers and follow-up items
- Link to related tasks and PRs

### DON'T:
- Create trivial entries for minor actions
- Duplicate similar entries
- Include unnecessary detail
- Auto-create without user confirmation

## Time Handling

- Use current system time for new entries
- Journal files use date-based filenames (`YYYYMMDD`)
- Times are naive (no timezone) per org-mode conventions

## File Management

- Files are created automatically if they don't exist
- Date heading (`* YYYY-MM-DD`) is added automatically
- Multiple entries per day are appended chronologically
