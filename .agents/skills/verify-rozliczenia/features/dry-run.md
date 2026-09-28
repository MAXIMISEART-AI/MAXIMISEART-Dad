# Dry-run planning

Dry-run lets the user inspect the planned settlement without changing worker
workbooks, while still exposing validation issues and local run telemetry.

## Sub-features

- `dry-run-validation` validates the source name, period folder, headers, templates, and mapping.
- `dry-run-plan` reports planned mapped templates and an empty template.
- `dry-run-no-write` leaves workbook input cells unchanged.
- `dry-run-metrics` records a `DRY-RUN` telemetry entry without customer row contents.

## How to get to it (user POV)

- Run `py -3 run.py --source <source> --config <mapping> --metrics <metrics> --dry-run` in a terminal.
- The CMD and VBA launchers do not expose a dry-run flag; use the direct CLI for this safety check.

## Driving it with PowerShell and run.py

Preconditions:

- The repository is clean enough to create a disposable `.verification` run.
- The orchestrator owns fixture creation, doctor setup, evidence paths, and cleanup.

- **Run the user command.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The orchestrator's `dry-run.txt` records the real command and expected exit code `2`.
- **Check the plan.** Read `dry-run.txt`; it contains `DRY-RUN`, `Planowane szablony: 2`, `Puste szablony: 1`, and `Nic nie zapisano`.
- **Check no workbook write.** Read `assert-dry-run.txt`; it contains `ASSERT OK` and exit code `0` after confirming `A18` is empty while `AU18` formulas remain.
- **Check telemetry.** Read the copied `metrics.jsonl` and inspect only JSON keys and counters. The record has mode `DRY-RUN`, `completed: true`, and no source path or row content.

## Gotchas

- Dry-run reads the source workbook and writes the metrics file; it is not a zero-I/O simulation.
- The expected exit code is `2`, not `0`, because the fixture deliberately tests an unmapped worker.
- Do not use the existence of a target workbook as proof that dry-run wrote it; the fixture creates empty templates before the command.
- A dry-run proof does not prove the later write path; run the worker-settlement feature separately.
