# Coding Standards

These standards are judgement calls for implementation and review.
They complement `GLOSSARY.md`, the ADRs, and the executable checks; they do not copy their contents.

## Domain Language

- Use the exact terms defined in `GLOSSARY.md` in issue titles, specifications, hypotheses, and test names.
  Treat `GLOSSARY.md` as the single source of truth for domain vocabulary instead of copying its term list here.
- Name tests after the domain behaviour they protect.
  Use an implementation name only when the test intentionally protects that module's interface.
- When implementation reveals a missing domain term, sharpen `GLOSSARY.md` before adding another synonym in code or tests.

## Module Depth

- Keep a coordinator responsible for sequencing, not for the details of the workbook it coordinates.
- A module with one main operation should expose that operation as its seam.
  Keep layout constants and helper functions private unless another module has a real reason to depend on them.
- Do not add a shared module only to avoid two small constants.
  Add one when it owns a coherent behaviour or a real variation.
- Keep the interface smaller than the implementation: callers should not need to know how a workbook is loaded, repaired, or saved atomically.
- In `src/`, a signature names its type instead of `Any`: the concrete type, `object`, or a `TypeVar` (ruff ANN401).

## Error Ownership

- Write a Komunikat's text only in a process's catalog (`preparation_messages`, `settlement_messages`).
  Two known exceptions wait for their own change: `WorkerConfigError.detail` and `PeriodFolderError.message`.
  Workbook code (`workbook_files` and the Sprawdzanie of each Wzorzec) raises `WorkbookError`, and each caller translates the error with one catalog function.
  That function ends its `match` on `Problem` with `assert_never`, so mypy rejects a new `Problem` until every catalog handles it.
  Other code calls its catalog's factories directly, and a process summary reports its problems as warning Komunikaty in `warnings`.
- Never decide on a Komunikat's code outside a catalog, and never map a code back to the fact that produced it.
  A process's plan returns typed facts (`preparation_plan.Plan.incomplete_period`, `preparation_files.CollectiveFilePlan`), and one place per process translates them into warnings, Zatrzymania, the result and Decyzja taty: `collective_preparation` and `engine`.
  A catalog factory takes facts (row numbers, column letters, dates), not layout types.
  `tests/test_decyzje_na_faktach.py` rejects a comparison or `match` on `.code` in the engine (`src/rozliczenia/*.py`).
  Centrum rozliczeń still decides on two codes until its own change: `NEWER_TOOL_VERSION` in `centrum/diagnosis.py` and `_RETRIED_BY_TATA` in `centrum/tool_updates.py`.
- Classify failures that can invalidate a write as typed critical exceptions.
  This includes preparing or restoring `xl/externalLinks/*`, not only the final filesystem replacement.
- Preserve `Nienadpisywanie`: existing input data is reported and never replaced automatically.
- Code in `src/` does not `print` (ruff T201), because Dad never sees a console and a problem reaches him as a Komunikat; only `launcher.py` and `shortcut.py` print to the start console.
- Pass `check=True` to `subprocess.run` unless the code after it reads `returncode`, and never write `check=False` only to silence ruff's PLW1510.
- Pass `strict=True` to `zip` when both sides must have the same length (ruff B905), `strict=False` only with a comment naming the check that already reports a different length, and use `itertools.pairwise` for successive pairs (RUF007).
- Name the time zone of every current day or moment (ruff DTZ): `datetime.now(timezone.utc)` for a moment that is stored or compared, and `datetime.now().astimezone().date()` for tata's local day.

## Test Surface

- Test each process through its operation (`run_settlements()`, `prepare_collective_file()`).
  Give a module with one entry point (one operation or the HTTP API of Centrum rozliczeń) its own tests only for behaviour that entry point cannot reach.
- A module whose interface at least two entry points call (two processes, or a process and Centrum rozliczeń) is a seam: test its rule matrix once, on its interface.
  Each entry point that uses it has one translation test (module error → that entry point's Komunikat) and does not repeat the matrix.
- Test Centrum rozliczeń through its HTTP API, the way the browser sees it: responses, the event stream, files on disk, metrics records.
  Prove UI behaviour in the browser with `verify-centrum-rozliczen`, not with component unit tests.
- Use synthetic workbook fixtures only.
  Cover both successful and failure paths for each operation's behaviour matrix.
- The test that owns a workbook write verifies values `A:AT`, preserved formulas and formatting, atomic replacement, and every entry under `xl/externalLinks/*`.
  Other tests assert only the behaviour they name.
- Keep tests free of client addresses, order numbers, and row contents in output or logs.
  The one exception is the Zatrzymanie about gaps in `SKUTECZNE` (`ZLE_SKUTECZNE`, ADR 0004): its tests use synthetic `SKUTECZNE` values, because the Komunikat shows the exact cell content.
- Before real files are used, run a preview without saving (`Podgląd bez zapisu`).
- Name a file that a test reads or runs with a literal path (`ROOT / "docs" / "adr"`), not a path built from a variable.
  `tools/szybko.py` selects tests from imports and such literals, so a path built at run time hides the dependency.
- Expect the error a test is about, not any error of its class: `pytest.raises` of a broad exception (`ValueError`, `OSError`) takes `match=` on its message, and the block holds the one statement that raises (ruff PT011, PT012).
- Prove that a new test or check fails on the broken code it guards with `tools/mutacje.py`.
  It mutates a copy of the checkout, never the checkout.
  Run it once for each test or check added or changed in a round of work.
  A rebase, or a fix that leaves the test unchanged, does not need a new run.

## Frontend

- The browser holds no domain logic: it displays what the server returns and sends tata's choices back.
  A rule needed in the UI belongs in the engine.
- Parse every server response and stream event at the browser boundary with the schemas generated from the server models.
  Change the contract on the server and regenerate; keep hand-written types for the UI's own state only.
  Only the files in `NETWORK_FILES` (`frontend/scripts/rules.mjs`), each with its reason, reach the network or call `JSON.parse` (`npm run rules`): a new endpoint gets a function in `src/api/centrum.ts` that goes through `call` with its schema.
- Model the UI states of an Uruchomienie procesu as one discriminated union that mirrors the progress projection's snapshot.
- Use components from the official `@shadcn` registry and semantic theme tokens.
  Write all UI text in Polish, in the vocabulary of `GLOSSARY.md` and the user guide.
- Display every contract field the UI receives, or remove it from the contract.
- Take limits and value sets shared with the server from the generated schemas, never from a repeated literal.
  Key a cache or a remount by exactly the fields whose change requires a new read (tata's files, not the theme).
- Build new UI to the accepted [v3 brief](https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad/issues/90#issuecomment-6257321289) with the `emil-design-eng` skill.

## Review Context

- Read `GLOSSARY.md` and the relevant ADR before changing a domain seam.
- Treat ADR 0001 as the constraint that Python remains the single source of settlement rules, and ADR 0003 as the constraint that there is no VBA adapter.
- Treat ADR 0004 as the constraint that Centrum rozliczeń is an adapter of Uruchomienie procesu, not a second process: it talks to the same core as the machine script, keeps no rules of its own, renders only the progress projection's snapshots and the process's shared messages as three-part structures.
  Review every Centrum change for localhost-only listening, `Host`/`Origin` checks, and file actions limited to paths the server derived from the periods folder.
- Treat ADR 0010 as the constraint that Centrum rozliczeń is Dad's only entry: there are no `.cmd` launchers and Dad's manual describes only Centrum.
- Treat ADR 0011 as the constraint that the processes have one conversation, Centrum rozliczeń: there is no CLI and no terminal adapter, and a Komunikat has only its three parts.
  E2E, the timing guard and the benchmark run the processes through the machine script `tools/uruchom_proces.py`, which uses the same core as Centrum and prints the Centrum contract as JSON.
- Do not leave a TODO, FIXME, XXX or HACK in the code (ruff FIX001-FIX004): finish it in the same change or name it in the report for Maks.
- Review standards separately from specification compliance.
  A passing test suite does not replace a review of module depth, seam locality, or domain vocabulary.
