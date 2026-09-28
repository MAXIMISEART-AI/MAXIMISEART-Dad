---
name: verify-rozliczenia
description: Verify MAXIMISEART-Dad's terminal settlement CLI by running synthetic Excel settlements, checking workbook side effects, and preserving evidence; use after CLI, workbook, or safety-rule changes.
---

# Verify rozliczenia

This is a short-lived Windows CLI, not a server. The primary user surface is
`run.py`; `Utwórz rozliczenia.cmd` and `deploy/AutomatyzacjaRozliczen.bas` are
alternate launchers for the same Python engine. The verification harness uses
synthetic `.xlsx` files only and never uses a real customer workbook.

## Launch

Run this one command from the repository root in PowerShell:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py
```

The runner creates unique scratch and evidence directories, sets UTF-8
environment variables, creates the synthetic fixture, runs the doctor, drives
the real CLI through dry-run and write modes, checks workbook side effects, and
cleans the scratch directory in `finally`. A successful run prints
`VERIFY OK`, an evidence path, and `scratch_removed=true`. The default fixture
intentionally contains one unmapped synthetic worker, so both CLI invocations
return semantic exit code `2`; this is expected and is asserted.

Use these variants for the safety-gate features:

```powershell
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing
py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked
```

`existing` seeds input in Adrian's template and verifies it is not overwritten.
`locked` runs the doctor before creating Darek's Excel lock file, then verifies
the lock is reported while other templates continue.

There is no server, port, login, seed database, or persistent instance. The
runner's subprocess timeout is 120 seconds; a timed-out child is terminated by
the process handle and the scratch cleanup still runs.

## Doctor

The runner always executes the read-only doctor before driving the application.
The result is retained in `doctor.txt` under the printed evidence directory.
`DOCTOR OK` means Python is at least 3.11, the checked-out build reports the
version in `pyproject.toml`, the source name and period folder agree, the source
has `WYKONAWCA` in `H17`, the local mapping is readable, every target workbook
has the expected header, and no Excel lock file is present at that point.

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

1. Create a disposable source workbook, three worker templates, a placeholder,
   and a local three-entry mapping.
2. Run the read-only doctor.
3. Run `run.py --dry-run`, require exit code `2`, and assert no workbook input
   cells changed.
4. Run `run.py` without `--dry-run`, require exit code `2`, and assert mapped
   values, preserved `AU` formulas, an empty mapped template, and an untouched
   placeholder.
5. Copy metrics to evidence and invoke the safe cleanup helper in `finally`.
6. Run the mechanical self-test against the retained evidence.

Each subprocess is recorded with its command, stdout, stderr, and exit code in
UTF-8 evidence files. The default fixture must report two mapped writes, one
`PUSTY_SZABLON`, one unmapped-worker issue, and progress `3/3 (100%)`.

The CMD launcher can be smoke-tested separately with a fresh fixture:

```powershell
cmd /c "Utwórz rozliczenia.cmd" "$source"
```

It has no `--config` or `--metrics` flags. The VBA route is the
`UruchomRozliczenia` macro in `deploy/AutomatyzacjaRozliczen.bas`; it requires
desktop Excel and is not a headless harness surface. Both adapters delegate to
the same Python engine.

## Evidence

Evidence is written under `.verification\evidence\` and survives cleanup. A
successful default run contains:

- `fixture.txt` with fixture creation output.
- `doctor.txt` with the read-only preflight result.
- `dry-run.txt` with the dry-run command, stdout, stderr, and exit code `2`.
- `assert-dry-run.txt` with the no-write workbook assertion and exit code `0`.
- `run.txt` with the real command, stdout, stderr, and exit code `2`.
- `assert-run.txt` with workbook side-effect assertions and exit code `0`.
- `metrics.jsonl` with safe local telemetry and no source path or row content.
- `cleanup.txt` with cleanup output and exit code `0`.
- `self-test.txt` with the skill and evidence invariant check.

The proof exercises the real user path, captures the action and resulting state,
and verifies filesystem side effects alongside terminal output. The dry-run
still reads workbooks and writes local metrics, so those effects are asserted
instead of inferred from the mode name. Mocks are not used.

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
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\assert_results.py --root "$runRoot" --expect run`.
- `scripts/cleanup.py` removes only a run root below `.verification\runs\`.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\cleanup.py --root "$runRoot"`.
- `scripts/self_test.py` checks the skill package and evidence hygiene.
  Invocation: `py -3 .agents\skills\verify-rozliczenia\scripts\self_test.py --evidence-root "$evidenceRoot"`.

Read `features/README.md` before choosing a feature. Keep the feature map
updated when routes, command flags, workbook rules, or adapter entry points
change. Use `/maintain-verification-skill` for the maintenance loop.
