# Coding Standards

Rules for writing and reviewing code and tests.
A rule that a check enforces sits in its section's table, one line per rule, beside the check that guards it.

## Domain Language

- Read `GLOSSARY.md` and the relevant ADR in `docs/adr/` before changing a domain seam.
- Use the exact terms defined in `GLOSSARY.md` in issue titles, specifications, hypotheses, and test names.
  `GLOSSARY.md` is the single source of truth for domain vocabulary.
- Name tests after the domain behaviour they protect.
  Use an implementation name only when the test intentionally protects that module's interface.
- When implementation reveals a missing domain term, sharpen `GLOSSARY.md` before adding another synonym in code or tests.

| Rule | Guard |
|---|---|
| An ADR number is unique and matches the file's heading. | `tests/test_adr.py` |
| A concept retired by an ADR (CLI, terminal, Rich, `run.py`, Dad's `.cmd` launchers) stays retired. | `tests/test_wycofane_pojecia.py` |

## Module Depth

- Keep a coordinator responsible for sequencing, not for the details of the workbook it coordinates.
- A module with one main operation should expose that operation as its seam.
  Keep layout constants and helper functions private unless another module has a real reason to depend on them.
- Add a shared module when it owns a coherent behaviour or a real variation, not to share two small constants.
- Keep the interface smaller than the implementation: callers should not need to know how a workbook is loaded, repaired, or saved atomically.
- In `src/`, a signature names its type instead of `Any`: the concrete type, `object`, or a `TypeVar` (ruff ANN401).

| Rule | Guard |
|---|---|
| The engine (`src/rozliczenia/*.py`) never imports Centrum rozliczeń, the modules in `STDLIB_ONLY` import only the standard library and each other when loaded, and the modules of the restart guardian's copy (`_COPIED` in `restart_guardian.py`) import only the standard library and `_COPIED`. | `tests/test_granice_importow.py` |

## Error Ownership

- Write a Komunikat's text only in a process's catalog (`preparation_messages`, `settlement_messages`).
  Two known exceptions wait for their own change: `WorkerConfigError.detail` and `PeriodFolderError.message`.
  Workbook code (`workbook_files`, `template_file`) raises `WorkbookError`, and each caller translates the error with one catalog function.
  The files that Sprawdzanie reads go through `input_checks`, which translates their reader errors once for both processes, the Diagnoza and the Konfiguracja.
  That function ends its `match` on `Problem` with `assert_never`, so mypy rejects a new `Problem` until every catalog handles it.
  Other code calls its catalog's factories directly, and a process summary reports its problems as warning Komunikaty in `warnings`.
- Only a catalog decides on a Komunikat's code, and no code maps a code back to the fact that produced it.
  The facts are typed (`preparation_plan.Plan.incomplete_period`, `preparation_files.CollectiveFilePlan`), and a catalog factory takes facts (row numbers, column letters, dates), not layout types.
  Centrum rozliczeń still decides on two codes until its own change: `NEWER_TOOL_VERSION` in `centrum/diagnosis.py` and `_RETRIED_BY_TATA` in `centrum/tool_updates.py`.
- Classify failures that can invalidate a write as typed critical exceptions.
  This includes preparing or restoring `xl/externalLinks/*`, not only the final filesystem replacement.
- Preserve `Nienadpisywanie`: existing input data is reported and never replaced automatically.
- Code in `src/` does not `print` (ruff T201), because Dad never sees a console and a problem reaches him as a Komunikat; only `launcher.py` and `shortcut.py` print to the start console.
- Pass `check=True` to `subprocess.run` unless the code after it reads `returncode`, and never write `check=False` only to silence ruff's PLW1510.
- Pass `strict=True` to `zip` when both sides must have the same length (ruff B905), `strict=False` only with a comment naming the check that already reports a different length, and use `itertools.pairwise` for successive pairs (RUF007).
- Name the time zone of every current day or moment (ruff DTZ): `datetime.now(timezone.utc)` for a moment that is stored or compared, and `datetime.now().astimezone().date()` for tata's local day.

| Rule | Guard |
|---|---|
| A file or folder of Dad's in a bad state (corrupt, with a BOM, in UTF-16, without access) gives a Komunikat that names it, and a file without access is „niedostępny” in it, never „uszkodzony”: read a workbook through `_file_bytes` (`workbook_files.py`) and a period folder through `reading` (`period_folder.py`). | `tests/test_uszkodzone_wejscia.py`, `tests/test_jeden_odczyt_skoroszytu.py` |
| Only `template_file.py`, `template_copy.py`, `row_look.py`, `workbook_save.py` and `intermax_file.py` write a workbook. | `tests/test_jeden_zapis_skoroszytu.py` |
| The engine decides on the facts of a process's plan, never on a Komunikat's code: one place per process (`collective_preparation`, `engine`) translates the facts into warnings, Zatrzymania, the result and Decyzja taty. | `tests/test_decyzje_na_faktach.py` |

## Test Surface

- Test each process through its operation (`run_settlements()`, `prepare_collective_file()`).
  Give a module with one entry point (one operation or the HTTP API of Centrum rozliczeń) its own tests only for behaviour that entry point cannot reach.
- A module whose interface at least two entry points call (two processes, or a process and Centrum rozliczeń) is a seam: test its rule matrix once, on its interface.
  Each entry point that uses it has one translation test (module error → that entry point's Komunikat) and does not repeat the matrix.
- Test Centrum rozliczeń through its HTTP API, the way the browser sees it: responses, the event stream, files on disk, metrics records.
  Prove UI behaviour in the browser with `verify-centrum-rozliczen`, not with component unit tests.
- Make the Rejestr zleceń or a Wzorzec fail in a test through a failing adapter of `input_checks.Readers`, not by patching a module attribute.
  The same `Readers` reach the Uruchomienie procesu, the Diagnoza and the Konfiguracja, so the fault reaches all three.
- Use synthetic workbook fixtures only.
  Cover both successful and failure paths for each operation's behaviour matrix.
- The test that owns a workbook write verifies values `A:AT`, preserved formulas and formatting, atomic replacement, and every entry under `xl/externalLinks/*`.
  Other tests assert only the behaviour they name.
- Keep tests free of client addresses, order numbers, and row contents in output or logs.
  The one exception is the Zatrzymanie about gaps in `SKUTECZNE` (`ZLE_SKUTECZNE`, ADR 0004): its tests use synthetic `SKUTECZNE` values, because the Komunikat shows the exact cell content.
- Before real files are used, run a preview without saving (`Podgląd bez zapisu`).
- Name a file that a test reads or runs with a literal path (`ROOT / "docs" / "adr"`), not a path built from a variable.
  `tools/szybko.py` selects tests from imports and such literals, so a path built at run time hides the dependency.
- Use an expect test (`assert_expected` in `tests/fixtures/expect.py`) for behaviour a human reads, such as Komunikaty and traces: it compares the text with a file in `tests/expected/`, named by a literal path.
  Write the new file with `ZAPISZ_EXPECT=1 .venv/bin/python -m pytest <test>`, which the failing test prints, and commit it with the change; CI never writes it.
- Test a rule that matches text from Dad's files (a word or phrase in `URZĄDZENIA` or `CZYNNOŚCI`, an operator name, a period token) with a Hypothesis property, not only with examples: the text anywhere in the cell, glued to punctuation, in any letter case and with Polish letters, two words of the rule in one cell, and the word inside a longer word.
  Take the expected result from `GLOSSARY.md`, the ADR or the docstring, and keep the examples deterministic with `derandomize=True` and `database=None`, as `tests/test_wlasnosci_dopasowania_tekstu.py` does.
- Expect the error a test is about, not any error of its class: `pytest.raises` of a broad exception (`ValueError`, `OSError`) takes `match=` on its message, and the block holds the one statement that raises (ruff PT011, PT012).
- Prove that a new test or check fails on the broken code it guards with `tools/mutacje.py`, the repository's one mutation engine: use it rather than writing another; to check every commit of a branch use `tools/ci_lokalnie.py --kazdy-commit`, not `git rebase --exec`.
  Run it once for each test or check added or changed in a round of work.
  A rebase, or a fix that leaves the test unchanged, does not need a new run.
- A mutation that `tools/mutacje_zmiany.py` reports as `NIEWYKRYTA` is behaviour without a test.
  The nightly run on `main` files each one as a line `MUTACJA <id>` in the issue `Przeżyte mutacje z #N` of the PR that last changed its line (ADR 0021): add the test that catches it, or answer the line with `MUTACJA <id> | nie warto, bo <reason>`.
  Only a mutation that leaves the behaviour unchanged gets `# mutacje-zmiany: <reason> | do YYYY-MM-DD | zgoda <who>` on its line, with Maks's approval.
- A PR that adds or changes a check (a structure test, a lint rule, a CI job, a checking tool) shows its result on real history in the PR body, from `tools/na_scalonych_pr.py`.
  On the commits of the PRs whose review found the mistake (`--commit <SHA>`), it finds what the review found.
  On a few recent merged PRs (`--ostatnie 5`), including one with Windows-only code, it raises no false alarm.
  The reviewer reruns at least one of these.

| Rule | Guard |
|---|---|
| Every changed line of `src/` and `tools/` has a test that fails when the line is broken, or its issue `Przeżyte mutacje z #N` says in a `MUTACJA` line why the test is not worth it („nie warto, bo …”), and the PR body promises only what the mutations confirm. | `tools/mutacje_zmiany.py` and `tools/mutacje_nocne.py` (nightly workflow `mutacje-nocne.yml`), `tests/test_mutacje_nocne.py` |
| A change to a Komunikat's text changes `tests/expected/komunikaty.txt` in the same PR. | `tests/test_komunikaty_expect.py` |
| A test module imports helpers only from `tests/fixtures`. | `tests/test_struktura_testow.py` |
| A test waits for a state of Centrum rozliczeń or measures time with the test's clock, and checks the time of the code under test by equality on the fake clock `ManualClock` (`tests/fixtures/clock.py`), never by a fixed number of milliseconds. | `tests/test_struktura_testow.py` |
| Git in tests has one configuration, the same on every computer: a test builds `env=` from `os.environ` and leaves `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM` alone, sets a computer configuration with something more through `computer_git_config` (`tests/fixtures/git_config.py`), and a process of the tool's code (`src/`) has an empty `user.name` and `user.email`, so its `git commit` fails as it does at Dad's. | fixture `git_bez_konfiguracji_komputera` in `tests/conftest.py`, `tests/test_git_w_testach.py` |
| A test named in a rules table (this file, `AGENTS.md`, `docs/agents/pr-i-ci.md`, `docs/agents/skille.md`) that checks the whole repository runs on every `tools/szybko.py`. | `tests/test_szybko.py` |

## Tools and Platforms

| Rule | Guard |
|---|---|
| Check the operating system with `sys.platform == "win32"`. | ruff `TID251` (`pyproject.toml`), mypy for both systems in `tools/ci_lokalnie.py` |
| A command of a tool in `tools/` that takes time or starts its own processes runs through `potomne.run`, and a copy of a commit comes from `potomne.commit_copy` ([`tools/potomne.py`](tools/potomne.py)), because they die together with the tool, even one killed by SIGKILL. | `tests/test_potomne.py` |
| A concurrent mutation run (`tools/mutacje.py --rownolegle`, a skill's `check_all`) runs at most `PARALLEL` mutations at once and gives each mutation's command `PYTEST_XDIST_AUTO_NUM_WORKERS=1` unless the caller set it, so a test's nested `pytest -n auto` does not multiply over the cores of the Mac that agents share. | `tests/test_mutacje.py` |
| The files that the system Python runs before `.venv` (the list in `per-file-target-version` in `pyproject.toml`) work under the Python 3.9 of macOS. | ruff `per-file-target-version`, `tests/test_systemowy_python.py` |
| A tool or skill script that runs as its own process adds `src` to `sys.path` itself, because CI on Windows does not install the package. | `tests/test_skrypty_bez_instalacji.py` |

## Frontend

- The browser holds no domain logic: it displays what the server returns and sends tata's choices back.
  A rule needed in the UI belongs in the engine.
- Change the contract on the server, and keep hand-written types for the UI's own state only.
  A new endpoint gets a function in `src/api/centrum.ts` that goes through `call` with its schema.
- Model the UI states of an Uruchomienie procesu as one discriminated union that mirrors the progress projection's snapshot.
- Use components from the official `@shadcn` registry and semantic theme tokens.
  Write all UI text in Polish, in the vocabulary of `GLOSSARY.md` and the user guide.
- Display every contract field the UI receives, or remove it from the contract.
- Take limits and value sets shared with the server from the generated schemas, never from a repeated literal.
  Key a cache or a remount by exactly the fields whose change requires a new read (tata's files, not the theme).
- Build new UI to the accepted [v3 brief](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/90#issuecomment-6257321289) with the `emil-design-eng` skill.

| Rule | Guard |
|---|---|
| The frontend reaches the server (`fetch`, `EventSource`, `WebSocket`, `XMLHttpRequest`, `sendBeacon`) and calls `JSON.parse` only in the files of `NETWORK_FILES`, which parse every server response and stream event with a schema generated from the server models. | `npm run rules` (rule 3 in `frontend/scripts/rules.mjs`) in CI job `Frontend` |
| After a change to the server models, and after a merge or a rebase, regenerate the contract and the Centrum build (`npm run regen` in `frontend/`), because the `merge=wygenerowane` driver keeps the current HEAD's version of them. | step „Require the committed contract and build to be fresh” of CI job `Frontend` |

## Review Context

- Treat ADR 0001 as the constraint that Python remains the single source of settlement rules, and ADR 0003 as the constraint that there is no VBA adapter.
- Treat ADR 0004 as the constraint that Centrum rozliczeń is an adapter of Uruchomienie procesu, not a second process: it talks to the same core as the machine script, keeps no rules of its own, renders only the progress projection's snapshots and the process's shared messages as three-part structures.
  Review every Centrum change for localhost-only listening, `Host`/`Origin` checks, and file actions limited to paths the server derived from the periods folder.
- Treat ADR 0010 as the constraint that Centrum rozliczeń is Dad's only entry: there are no `.cmd` launchers and Dad's manual describes only Centrum.
- Treat ADR 0011 as the constraint that the processes have one conversation, Centrum rozliczeń: there is no CLI and no terminal adapter, and a Komunikat has only its three parts.
  E2E, the timing guard and the benchmark run the processes through the machine script `tools/uruchom_proces.py`, which uses the same core as Centrum and prints the Centrum contract as JSON.
- Finish a TODO, FIXME, XXX or HACK in the same change or name it in the report for Maks; ruff FIX001-FIX004 rejects it in the code.
- Review standards separately from specification compliance.
  A passing test suite does not replace a review of module depth, seam locality, or domain vocabulary.
