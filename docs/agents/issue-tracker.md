# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in
[MAXIMISEART-AI/MAXIMISEART-Dad](https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad).
Use the `gh` CLI for all operations.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- Read an issue with `gh issue view <number> --comments`.
- List issues with `gh issue list`, using JSON output when comments and labels are needed.
- Comment with `gh issue comment <number> --body "..."`.
- Apply or remove labels with `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close an issue with `gh issue close <number> --comment "..."`.
- Infer the repository from the Git remote; `gh` runs inside this clone.

## Specs, sub-issues, and dependencies

- A published spec is the parent issue. Tickets derived from it must be native
  GitHub sub-issues of that parent, not standalone issues with only a textual
  parent link.
- Publish tickets in dependency order: create blockers first, then tickets that
  depend on them.
- After creating a ticket, retrieve its numeric GitHub issue ID before creating
  relationships:

  ```powershell
  gh api repos/OWNER/REPO/issues/NUMBER --jq '.id'
  ```

- Add a ticket as a sub-issue of the spec with the parent issue number and the
  child's numeric issue ID:

  ```powershell
  gh api repos/OWNER/REPO/issues/PARENT/sub_issues `
    --method POST --field sub_issue_id=CHILD_ISSUE_ID
  ```

- Add each blocking edge to the blocked ticket. For example, if ticket 12 is
  blocked by ticket 11, post ticket 11's numeric issue ID to ticket 12:

  ```powershell
  gh api repos/OWNER/REPO/issues/12/dependencies/blocked_by `
    --method POST --field issue_id=BLOCKER_ISSUE_ID
  ```

- Keep a human-readable `Blocked by` section in each ticket body, but treat it as
  documentation only. The native sub-issue and dependency relationships are the
  source of truth.
- Verify the final graph after publishing:

  ```powershell
  gh api repos/OWNER/REPO/issues/PARENT/sub_issues
  gh api repos/OWNER/REPO/issues/NUMBER/dependencies/blocked_by
  ```

- GitHub issue IDs are 64-bit values. Pass them to `gh api` as numeric fields
  without narrowing them to a 32-bit integer.

## Pull requests as a triage surface

PRs as a request surface: no.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

When the source is an existing spec issue, create the resulting tickets as
native sub-issues and apply their native dependency edges before reporting the
work complete.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

The `/wayfinder` skill uses one map issue with child issues as tickets. Use
GitHub sub-issues and native issue dependencies where available. If those
features are unavailable, record the relationship in the issue body.
