---
name: verify-rozliczenia
description: Verify MAXIMISEART-Dad's CMD-launched processes (Przebieg rozliczeń, Przygotowanie pliku zbiorczego) with synthetic Excel files, workbook side-effect checks, and retained evidence; use after CLI, workbook, or safety-rule changes.
---

# Verify rozliczenia

This is a short-lived Windows CLI, not a server. Dad has two launchers:
`Utwórz rozliczenia.cmd` starts `run.py` (Przebieg rozliczeń), and
`Przygotuj plik zbiorczy.cmd` starts `run_preparation.py` (Przygotowanie pliku
zbiorczego). The verification harness also drives each CLI directly for
detailed assertions. The VBA adapter is legacy and
outside the supported user workflow. Verification uses synthetic `.xlsx` files
and never uses a real customer workbook; the one exception is the local
`preparation-real-templates` variant, which copies the real Wzorce from
`config/`.

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

Drive the supported CMD launcher separately with its isolated synthetic runtime:

```powershell
py -3 -m pytest tests/test_cmd_launcher.py::test_cmd_launcher_runs_przebieg_rozliczen -q
```

The test copies the launcher and engine into a disposable runtime with a
synthetic mapping and Wzorzec rozliczenia pracownika, then checks the command result and workbooks.

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
Its route, counts, and launcher test are in `features/prepare-collective-file.md`.

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
worktree, pass `--templates-dir <main checkout>\config`. Without both Wzorce
the runner prints `VERIFY SKIP` and exits `0`; report that as a skip, never as
a proof.

Before handing work over, run every CI variant in one command, as CI does:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant all
```

On macOS or Linux, replace `py -3` with `.venv/bin/python`; README.md covers
the `.venv` setup.

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
not yet exist.

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

Each subprocess is recorded with its command, stdout, stderr, and exit code in
UTF-8 evidence files. The default fixture reports two mapped writes, one
`PUSTY_SZABLON`, no issues, and progress `3/3 (100%)`. The `unmapped` variant
proves that the dry-run warns and the real run publishes nothing.

`Utwórz rozliczenia.cmd` has no `--config` or `--metrics` flags;
`Przygotuj plik zbiorczy.cmd` passes all its arguments to `run_preparation.py`. The VBA module remains
in the repository as a legacy adapter; it is not part of the Dad-facing route
or required verification coverage unless the user reactivates it.

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

The CLI proof captures the action and resulting state and verifies filesystem
side effects alongside terminal output. The CMD smoke test separately drives
the supported launcher in an isolated runtime. The dry-run still reads
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
  both Wzorce, and the mapping for the `preparation` variant; with
  `--templates-from "$templatesDir"` it copies the real Wzorce instead.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\create_preparation_fixture.py --root "$runRoot"`.
- `scripts/preparation_doctor.py` performs the read-only preflight for that fixture.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\preparation_doctor.py --root "$runRoot" --expected-version "0.1.0"`.
- `scripts/assert_preparation.py` checks the Folder okresu, both period files,
  external links, inputs, transcript, and metrics; `--templates config` swaps
  the synthetic Wzorzec checks for the generic real-Wzorzec checks.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_preparation.py --root "$runRoot" --expect run --transcript "$evidenceRoot\run.txt"`.
- `scripts/cleanup.py` removes only a run root below `.verification\runs\`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"`.
- `scripts/self_test.py` checks the skill package and evidence hygiene.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"`.

Read `features/README.md` before choosing a feature. Keep the feature map
updated when routes, command flags, workbook rules, or adapter entry points
change. Use `/maintain-verification-skill` for the maintenance loop.
