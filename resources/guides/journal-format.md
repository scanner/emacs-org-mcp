# Journal Format

## Entry Format

`** HH:MM [TICKET-ID] headline :tags:`

```org
** 14:30 GH-127 [[https://github.com/org/repo/pull/221][#221]] Submitted OAuth2 PR
- Implemented Google and GitHub providers
- All tests passing
- Addresses [[file:~/org/tasks.org::#task-gh-127][GH-127 task]]
```

## Components

- **Time:** 24-hour format (`14:30`)
- **Ticket ID:** Optional (`GH-123`)
- **PR link:** Optional, inline (`[[url][#123]]`)
- **Tags:** Optional, at end (`:daily_summary:`, `:meeting:`, `:blocked:`, `:decision:`)

## Link Formats

- Task link: `[[file:~/org/tasks.org::#task-gh-123][Display]]`
- PR link: `[[https://github.com/org/repo/pull/123][#123]]`

## Guidelines

- Check existing entries before creating (avoid duplicates)
- Only create on explicit request or end-of-session summary
- Use bullets for details, focus on outcomes
- Batch related work into single entries
