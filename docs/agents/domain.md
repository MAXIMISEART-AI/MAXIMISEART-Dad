# Domain Docs

Engineering skills must read the domain documentation before exploring code.

## Before exploring

Read `CONTEXT.md` at the repo root and the relevant ADRs under `docs/adr/`.
If a required file does not exist, proceed silently.

## File structure

This is a single-context repository:

- `CONTEXT.md` contains the domain glossary.
- `docs/adr/` contains system-wide architectural decisions.
- There is no `CONTEXT-MAP.md` or context-specific ADR directory.

## Vocabulary

Use the glossary terms from `CONTEXT.md` for domain concepts in issue titles,
specifications, hypotheses, and test names. If a needed concept is missing,
treat that as a domain-modeling gap rather than silently inventing a synonym.

## ADR conflicts

If a proposal conflicts with an existing ADR, call out the conflict explicitly
instead of silently overriding the decision.
