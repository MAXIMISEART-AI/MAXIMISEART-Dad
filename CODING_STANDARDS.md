# Coding Standards

These standards are judgement calls for implementation and review. They
complement `CONTEXT.md`, the ADRs, and the executable checks; they do not copy
their contents.

## Domain Language

- Use the exact terms defined in `CONTEXT.md` in issue titles, specifications,
  hypotheses, and test names. Treat `CONTEXT.md` as the single source of truth
  for domain vocabulary instead of copying its term list here.
- Name tests after the domain behaviour they protect. Use an implementation
  name only when the test intentionally protects that module's interface.
- When implementation reveals a missing domain term, sharpen `CONTEXT.md`
  before adding another synonym in code or tests.

## Module Depth

- Keep a coordinator responsible for sequencing, not for the details of the
  workbook it coordinates.
- A module with one main operation should expose that operation as its seam.
  Keep layout constants and helper functions private unless another module has
  a real reason to depend on them.
- Do not add a shared module only to avoid two small constants. Add one when it
  owns a coherent behaviour or a real variation.
- Keep the interface smaller than the implementation: callers should not need
  to know how a workbook is loaded, repaired, or saved atomically.

## Error Ownership

- Classify validation and inspection problems as safe `Issue` values when the
  process can continue with another Szablon pracownika.
- Classify failures that can invalidate a write as typed critical exceptions.
  This includes preparing or restoring `xl/externalLinks/*`, not only the final
  filesystem replacement.
- Preserve `Nienadpisywanie`: existing input data is reported and never
  replaced automatically.

## Test Surface

- Test module behaviour through its interface and test the full
  `run_settlements()` flow separately.
- Use synthetic workbook fixtures only. Cover both successful and failure
  paths for each operation's behaviour matrix.
- For workbook writes, verify values `A:AT`, preserved formulas and formatting,
  atomic replacement, and every entry under `xl/externalLinks/*`.
- Keep tests free of client addresses, order numbers, and row contents in
  output or logs.
- After changes, run the repository test command from `README.md`; before real
  files are used, run `--dry-run`.

## Review Context

- Read `CONTEXT.md` and the relevant ADR before changing a domain seam.
- Treat ADR 0001 as the constraint that Python remains the single source of
  settlement rules and that CMD and VBA invoke the same engine.
- Review standards separately from specification compliance. A passing test
  suite does not replace a review of module depth, seam locality, or domain
  vocabulary.
