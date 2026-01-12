# Complete Examples for emacs-org MCP

## Example Task Entry

### New Feature Task

```org
** TODO GH-127 Implement OAuth2 authentication flow
:PROPERTIES:
   :ID:       C79031AC-94FE-4FDD-BBBF-7D3EE1A881E9
   :CUSTOM_ID: task-gh-127
   :CREATED:  <2025-01-15 Wed 10:30>
   :MODIFIED: [2025-01-15 Wed 10:30>
:END:

*** Description

Implement OAuth2 authentication flow for user login. This will replace the
current basic auth system with a more secure OAuth2 implementation supporting
multiple providers (Google, GitHub, Microsoft).

*** Related Issues

- [[https://github.com/org/repo/issues/127][GH-127 - Add OAuth2 support]]
- [[https://github.com/org/repo/issues/98][GH-98 - Security audit recommendations]]

*** Related PRs

- [[https://github.com/org/repo/pull/221][#221 - Initial OAuth2 implementation]]

*** Task items [1/5]

- [X] Research OAuth2 libraries and create implementation plan
- [ ] Implement OAuth2 provider configuration
- [ ] Create authentication endpoints
- [ ] Add tests for authentication flow
- [ ] Update documentation

*** Notes

Using the authlib library for OAuth2 implementation.

Provider configuration will be stored in environment variables:
- OAUTH_GOOGLE_CLIENT_ID
- OAUTH_GOOGLE_CLIENT_SECRET
- OAUTH_GITHUB_CLIENT_ID
- OAUTH_GITHUB_CLIENT_SECRET
```

### Completed Bug Fix Task

```org
** DONE GH-98 Fix memory leak in background worker
:PROPERTIES:
   :ID:       A1B2C3D4-E5F6-7890-ABCD-EF1234567890
   :CUSTOM_ID: task-gh-98
   :CREATED:  <2025-01-10 Fri 14:00>
   :MODIFIED: [2025-01-14 Tue 16:45]
   :CLOSED:   <2025-01-14 Tue 16:45>
:END:

*** Description

Background worker was not properly closing database connections, leading to
connection pool exhaustion after ~2 hours of operation.

*** Related Issues

- [[https://github.com/org/repo/issues/98][GH-98 - Memory leak in production]]

*** Related PRs

- [[https://github.com/org/repo/pull/210][#210 - Fix database connection handling]]

*** Task items [3/3]

- [X] Reproduce issue in development environment
- [X] Identify root cause (missing connection.close() in error path)
- [X] Implement fix and verify with load testing

*** Notes

Root cause was exception handler not closing DB connections.
Verified fix with 12-hour load test.
```

## Example Journal Entries

### Daily Journal File (20250115)

```org
* 2025-01-15

** 09:30 GH-127 Started OAuth2 implementation planning
- Researched authlib vs oauthlib libraries
- Decided on authlib for better Flask integration
- Created implementation plan in [[file:~/org/tasks.org::#task-gh-127][GH-127 task notes]]

** 11:15 Code review for PR #215
- Reviewed authentication middleware changes
- Requested tests for edge cases
- Approved after updates

** 14:30 GH-127 [[https://github.com/org/repo/pull/221][#221]] Submitted OAuth2 PR for review
- Implemented Google and GitHub OAuth2 providers
- Added configuration via environment variables
- All tests passing, ready for review
- Addresses [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2 task]]

** 16:45 GH-98 [[https://github.com/org/repo/pull/210][#210]] Fixed memory leak :merged:
- PR merged to main
- Verified fix deployed to staging
- Monitoring shows stable connection pool
- Closes [[file:~/org/tasks.org::#task-gh-98][GH-98 bug fix task]]

** 17:30 Daily work summary :daily_summary:
- Completed OAuth2 implementation ([[file:~/org/tasks.org::#task-gh-127][GH-127]])
- Fixed critical memory leak ([[file:~/org/tasks.org::#task-gh-98][GH-98]] merged)
- PRs: [[https://github.com/org/repo/pull/221][#221]] submitted, [[https://github.com/org/repo/pull/210][#210]] merged
- Code review for authentication changes
- Tomorrow: Address PR #221 review feedback
```

### Entry with Multiple Task Links

```org
* 2025-01-15

** 15:00 Progress on multiple features
- Worked on [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2]] - completed provider config
- Fixed bug in [[file:~/org/tasks.org::#task-gh-130][GH-130 validation]] - ready for testing
- Reviewed [[file:~/org/tasks.org::#task-gh-125][GH-125 API refactor]] - approved
```

### Entry with Multiple PR Links

```org
* 2025-01-15

** 17:00 Submitted multiple PRs
- [[https://github.com/org/repo/pull/221][#221]] OAuth2 implementation (addresses [[file:~/org/tasks.org::#task-gh-127][GH-127]])
- [[https://github.com/org/repo/pull/222][#222]] Fix validation errors (addresses [[file:~/org/tasks.org::#task-gh-130][GH-130]])
- [[https://github.com/org/repo/pull/223][#223]] Update dependencies
- All passing CI checks
```

### Minimal Entry (No Ticket)

```org
* 2025-01-15

** 10:30 Updated dependencies
- Ran npm audit fix
- Updated React from 18.2.0 to 18.3.1
- No breaking changes, all tests pass
```

### Entry with Tags and Task Link

```org
* 2025-01-15

** 14:00 Architecture decision: Use Redis for caching :decision:architecture:
- Evaluated Redis vs Memcached
- Redis chosen for data persistence and pub/sub features
- Will implement in [[file:~/org/tasks.org::#task-gh-135][GH-135 caching task]]
- Starting sprint 3
```

## Creating Tasks

### Example: Creating a New Feature Task

```python
# 1. Check for duplicates
search_results = await search_tasks("OAuth2 authentication")

# 2. Create task (UUID auto-generated if not provided)
task_entry = """** TODO GH-127 Implement OAuth2 authentication flow
:PROPERTIES:
   :CUSTOM_ID: task-gh-127
:END:

*** Description

Implement OAuth2 authentication flow for user login.

*** Task items [/]

- [ ] Research OAuth2 libraries
- [ ] Implement authentication endpoints
- [ ] Add tests
"""

await create_task(section="Tasks", task_entry=task_entry)
```

### Example: Updating Task to Mark Complete

```python
# 1. Get current task
current_task = await get_task("GH-127")

# 2. Modify to DONE and update content
updated_entry = """** DONE GH-127 Implement OAuth2 authentication flow
:PROPERTIES:
   :ID:       C79031AC-94FE-4FDD-BBBF-7D3EE1A881E9
   :CUSTOM_ID: task-gh-127
   :CREATED:  <2025-01-15 Wed 10:30>
:END:

*** Description

Implement OAuth2 authentication flow for user login.

*** Related PRs

- [[https://github.com/org/repo/pull/221][#221 - OAuth2 implementation]]

*** Task items [3/3]

- [X] Research OAuth2 libraries
- [X] Implement authentication endpoints
- [X] Add tests
"""

# Automatically moves to Completed section, sets CLOSED and MODIFIED timestamps
await update_task("GH-127", task_entry=updated_entry)
```

## Creating Journal Entries

### Example: Journal Entry with Task Link

```python
from datetime import date, datetime

# 1. Check existing entries
existing = await list_journal_entries(date.today())

# 2. Create new entry with task link
await create_journal_entry(
    date=date.today(),
    time=datetime.now().strftime("%H:%M"),
    headline="GH-127 Submitted OAuth2 PR",
    content=(
        "- Implemented Google and GitHub providers\n"
        "- All tests passing\n"
        "- Addresses [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2 task]]"
    ),
    tags=[]
)
```

### Example: End-of-Day Summary with Multiple Links

```python
await create_journal_entry(
    date=date.today(),
    time=datetime.now().strftime("%H:%M"),
    headline="Daily work summary",
    content=(
        "- Completed [[file:~/org/tasks.org::#task-gh-127][GH-127 OAuth2 feature]]\n"
        "- Fixed [[file:~/org/tasks.org::#task-gh-98][GH-98 memory leak]]\n"
        "- PRs: [[https://github.com/org/repo/pull/221][#221]] submitted, "
        "[[https://github.com/org/repo/pull/210][#210]] merged\n"
        "- Tomorrow: Address PR feedback"
    ),
    tags=["daily_summary"]
)
```

### Example: Entry with PR Link

```python
await create_journal_entry(
    date=date.today(),
    time=datetime.now().strftime("%H:%M"),
    headline="GH-127 [[https://github.com/org/repo/pull/221][#221]] Submitted OAuth2 PR for review",
    content=(
        "- Implemented Google and GitHub OAuth2 providers\n"
        "- Added configuration via environment variables\n"
        "- All tests passing, ready for review"
    ),
    tags=[]
)
```
