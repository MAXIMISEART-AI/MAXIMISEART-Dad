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

## Pull requests as a triage surface

PRs as a request surface: no.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

The `/wayfinder` skill uses one map issue with child issues as tickets. Use
GitHub sub-issues and native issue dependencies where available. If those
features are unavailable, record the relationship in the issue body.
