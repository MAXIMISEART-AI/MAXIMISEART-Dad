---
name: verify-rozliczenia
description: Verify MAXIMISEART-Dad's processes (Przebieg rozliczeń, Przygotowanie pliku zbiorczego) through their CLI, each alone and chained from Rejestr zleceń to Rozliczenia pracowników, with synthetic Excel files, workbook side-effect checks, and retained evidence; use after CLI, workbook, or safety-rule changes.
---

# Verify rozliczenia

This is a short-lived Windows CLI, not a server: `run.py` runs Przebieg
rozliczeń and `run_preparation.py` runs Przygotowanie pliku zbiorczego. Dad
starts both processes in Centrum rozliczeń, which talks to the same core and is
verified by `verify-centrum-rozliczen`
([ADR 0010](../../../docs/adr/0010-centrum-jedynym-wejsciem-taty.md)). This
harness drives each CLI directly for detailed assertions. Verification uses synthetic `.xlsx` files
and never uses a real customer workbook; the only exceptions are the local
`preparation-real-templates` and `chain-real-templates` variants, which copy
the real Wzorce from `config/`.

## Launch

Run the direct CLI proof from the repository root in PowerShell:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py
```

The runner creates unique scratch and evidence directories, sets UTF-8
environment variables, creates the synthetic fixture, runs the doctor, drives
the real CLI through dry-run and write modes, checks workbook side effects, and
cleans the scratch directory in `finally`. A successful run prints
`VERIFY OK`, an evidence path, and `scratch_removed=true`. The default fixture
contains only mapped synthetic workers, so dry-run and write both return `0`.

Use these variants for publication and safety-gate features:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped
```

`existing` creates a conflicting output folder after the doctor and dry-run, then
verifies it is unchanged. `locked` locks the Wzorzec rozliczenia pracownika before the real run.
`unmapped` adds an unknown synthetic WYKONAWCA and verifies that no output is
published.

Use this variant after changes to Przygotowanie pliku zbiorczego:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation
```

`preparation` builds a synthetic Rejestr zleceń and both Wzorce, drives
`run_preparation.py` through dry-run and write, and checks both period files.
Its route and counts are in `features/prepare-collective-file.md`.

When `config/` holds the real Wzorce, also run the local variant after changes
to formatting or template handling in Przygotowanie pliku zbiorczego:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation-real-templates
```

It drives the same synthetic Rejestr into byte copies of both real Wzorce and
checks that the copies stay byte-identical, that every written data cell has
its header's font face and size, that every Wzorzec cell outside the written
rows is unchanged, and that `xl/externalLinks/*` stay byte-identical. The
Wzorce are git-ignored, so CI and `--variant all` leave this variant out. In a
worktree the runner reads the main checkout's `config/` itself;
`--templates-dir` overrides that. Without both Wzorce the runner prints
`VERIFY SKIP` and exits `0`; report that as a skip, never as a proof.

Use this variant after changes to either process, to the Plik zbiorczy layout,
or to the hand-over between the processes:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain
```

`chain` walks Dad's whole path in one run: Przygotowanie pliku zbiorczego from
the synthetic Rejestr zleceń (dry-run, then write), a Gotowość step that types
quantities into `N:AP` and charges and remarks into `AQ:AT` of three Wiersze
danych of the resulting Plik zbiorczy, then Przebieg rozliczeń on that file
(dry-run, then write). It checks that every Rozliczenie pracownika holds only
its Wykonawca's Zlecenia skuteczne in Plik zbiorczy order, with `A:AT` equal to
the Plik zbiorczy row, Gotowość entries included, and with the Wyróżnienia of
the Plik zbiorczy cells. `chain-real-templates` runs
the same path on byte copies of all three real Wzorce, including the Wzorzec
rozliczenia pracownika; like `preparation-real-templates` it is local only,
takes `--templates-dir`, and prints `VERIFY SKIP` without them. Route and
counts are in `features/prepare-and-settle.md`.

Before handing work over, run every CI variant in one command, as CI does:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant all
```

On macOS or Linux, replace `py -3` with `.venv/bin/python`; README.md covers
the `.venv` setup.

In a worktree, create its own `.venv` with `tools/setup_worktree.py` first:
the main checkout's `.venv` is an editable install of the main checkout's
`src`, so ad-hoc `python -c` there silently imports `main`'s code.

There is no server, port, login, seed database, or persistent instance. The
runner's subprocess timeout is 120 seconds; a timed-out child is terminated by
the process handle and the scratch cleanup still runs.

## Doctor

The runner always executes the read-only doctor before driving the application.
The result is retained in `doctor.txt` under the printed evidence directory.
`DOCTOR OK` means Python is at least 3.11, the checked-out build reports the
version in `pyproject.toml`, the source name and period folder agree, the source
has `WYKONAWCA` in `H17`, the local mapping and shared Wzorzec rozliczenia pracownika are readable,
and the target folder does not yet exist.

The `preparation` variant runs `preparation_doctor.py` instead. `DOCTOR OK`
there means the Rejestr has a sheet with all required headers, both Wzorce are
unlocked with their expected headers, the Wzorzec pliku zbiorczego has
`xl/externalLinks/*` parts, the mapping is readable, and the Folder okresu does
not yet exist. The `chain` variants pass `--with-worker-template`, which also
validates the Wzorzec rozliczenia pracownika the way `run.py` does.

For targeted debugging of a fixture that already exists, invoke the primitive
directly:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\doctor.py --root "$runRoot" --expected-version "0.1.0"
```

The doctor reads only; it does not start the app, alter a workbook, or write
metrics. Never drive a fixture that this run did not create.

## Drive

Use `run_verification.py` as the harness entry point. It launches the real
`run.py` CLI with the same selected Python interpreter as the harness, not
imports into `rozliczenia`, test-only helpers, or direct calls to the settlement
engine. Its ordered stages are:

1. Create a disposable source workbook, a shared Wzorzec rozliczenia pracownika, and a local
   three-entry mapping. The target folder is absent.
2. Run the read-only doctor.
3. Run `run.py --dry-run` with the synthetic Wzorzec rozliczenia pracownika and assert the complete
   plan, no target folder, unchanged source/Wzorzec rozliczenia pracownika, and no row content.
4. Run `run.py` normally; the default fixture requires exit code `0` and asserts
   exactly three workbooks, routed values, preserved formulas/formatting, an
   empty worker workbook, and an unchanged Wzorzec rozliczenia pracownika.
5. For `existing`, `locked`, or `unmapped`, require exit code `1` and assert no
   partial output is published (or an existing folder is left unchanged).
6. Copy metrics to evidence and invoke cleanup in `finally`, then run the
   mechanical self-test against the retained evidence.

The `preparation` variant follows the same stages with its own primitives:
`create_preparation_fixture.py`, `preparation_doctor.py`,
`run_preparation.py --dry-run`, `assert_preparation.py --expect dry-run`,
`run_preparation.py`, then `assert_preparation.py --expect run`. Both runs
require exit code `0`.

The `chain` variants run, in order: `create_preparation_fixture.py
--with-worker-template`, `preparation_doctor.py --with-worker-template`, the four
preparation steps above under a `preparation-` prefix with their own
`preparation-metrics.jsonl`, `fill_readiness.py` (Gotowość), `run.py --source
<the Plik zbiorczy written by Przygotowanie> --dry-run`, `assert_chain.py
--expect dry-run`, `run.py` on the same file, then `assert_chain.py --expect
run`. Every run requires exit code `0`.

Each subprocess is recorded with its command, stdout, stderr, and exit code in
UTF-8 evidence files. The default fixture reports two mapped writes, one
`PUSTY_SZABLON`, no issues, and progress `3/3 (100%)`. The `unmapped` variant
proves that the dry-run warns and the real run publishes nothing.

## Evidence

Evidence is written under `.verification\evidence\` and survives cleanup. A
successful default run contains:

- `fixture.txt` with fixture creation output.
- `doctor.txt` with the read-only preflight result.
- `dry-run.txt` with the dry-run command, stdout, stderr, and expected exit code.
- `assert-dry-run.txt` with the no-write workbook assertion and exit code `0`.
- `run.txt` with the real command, stdout, stderr, and expected exit code.
- `assert-run.txt` with workbook side-effect assertions and exit code `0`.
- `metrics.jsonl` with safe local telemetry and no source path or row content.
- `cleanup.txt` with cleanup output and exit code `0`.
- `self-test.txt` with the skill and evidence invariant check.

The `chain` variants name the steps of each process instead:
`preparation-dry-run.txt`, `assert-preparation-dry-run.txt`,
`preparation-run.txt`, `assert-preparation-run.txt`, `readiness.txt`,
`settlement-dry-run.txt`, `assert-settlement-dry-run.txt`,
`settlement-run.txt`, `assert-settlement-run.txt`, and two metrics histories,
`preparation-metrics.jsonl` and `settlement-metrics.jsonl`, each with one
`DRY-RUN` and one `RUN` record.

The CLI proof captures the action and resulting state and verifies filesystem
side effects alongside terminal output. The dry-run still reads
workbooks and writes local metrics, so those effects are asserted instead of
inferred from the mode name. Mocks are not used.

## Self-test

The complete runner invokes the mechanical skill check after cleanup. To check
an existing proof directly, run:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"
```

It checks the frontmatter, required feature-map headings, every documented
helper path, helper `--help` execution, strict UTF-8 evidence decoding, and
that cleanup preserves a separate evidence file. It also rejects the synthetic
fixture's source-row markers if they appear in evidence. The check reports only
file names and invariant failures, never the offending row value.

## Cleanup

The runner owns cleanup and invokes `cleanup.py` from a `finally` block after
both successful and failed workflow stages. It removes only the unique run root
under `.verification\runs\`; it never removes evidence. Do not kill processes
by name.

If the runner itself is force-terminated before its `finally` block executes,
run the primitive against the abandoned run root discovered under
`.verification\runs\`:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"
```

Then confirm the evidence directory still exists. A normal runner completion
already performs both checks and prints `scratch_removed=true`.

## Helpers

- `scripts/run_verification.py` is the one-command orchestrator. Invocation:
  `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`.
- `scripts/create_fixture.py` creates the isolated synthetic workbooks.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\create_fixture.py --root "$runRoot"`.
- `scripts/doctor.py` performs the read-only fixture and build check.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\doctor.py --root "$runRoot" --expected-version "0.1.0"`.
- `scripts/assert_results.py` checks workbook state after either mode.
  Dry-run additionally requires `--transcript`; write mode checks workbook state.
- `scripts/create_preparation_fixture.py` creates the synthetic Rejestr zleceń,
  both Wzorce, and the mapping for the `preparation` variant;
  `--with-worker-template` adds the Wzorzec rozliczenia pracownika for `chain`, and
  `--templates-from "$templatesDir"` copies the real Wzorce instead.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\create_preparation_fixture.py --root "$runRoot"`.
- `scripts/preparation_doctor.py` performs the read-only preflight for that fixture;
  `--with-worker-template` also validates the Wzorzec rozliczenia pracownika.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\preparation_doctor.py --root "$runRoot" --expected-version "0.1.0"`.
- `scripts/assert_preparation.py` checks the Folder okresu, both period files,
  external links, inputs, transcript, and metrics; `--templates config` swaps
  the synthetic Wzorzec checks for the generic real-Wzorzec checks, and
  `--metrics` reads a history other than `<root>\metrics.jsonl`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_preparation.py --root "$runRoot" --expect run --transcript "$evidenceRoot\run.txt"`.
- `scripts/fill_readiness.py` is the Gotowość step of `chain`: it fills `N:AT`
  in three Wiersze danych of the Plik zbiorczy, keeps every other cell and the
  external links, and records the period files' hashes for `assert_chain.py`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\fill_readiness.py --root "$runRoot"`.
- `scripts/assert_chain.py` checks the Przebieg rozliczeń of `chain` against
  the Plik zbiorczy it read: worker routing and order, `A:AT` equality of values
  and Wyróżnienia, Gotowość entries, no Zlecenie nieskuteczne, the preserved
  Wzorzec rozliczenia pracownika, unchanged inputs and period files, transcript,
  and metrics.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_chain.py --root "$runRoot" --expect run --transcript "$evidenceRoot\settlement-run.txt"`.
- `scripts/cleanup.py` removes only a run root below `.verification\runs\`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"`.
- `scripts/self_test.py` checks the skill package and evidence hygiene.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"`.

Read `features/README.md` before choosing a feature. Keep the feature map
updated when routes, command flags, workbook rules, or adapter entry points
change. Use `/maintain-verification-skill` for the maintenance loop.
