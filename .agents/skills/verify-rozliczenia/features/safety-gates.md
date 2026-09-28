# Safety gates

Safety gates prevent a settlement from guessing a worker, touching a
placeholder, overwriting existing input, or writing through an Excel lock.

## Sub-features

- `safety-unknown` reports and skips an unmapped source worker.
- `safety-placeholder` leaves the legacy no-worker workbook untouched and
  requires a valid shared Placeholder for `--dry-run`.
- `safety-target-folder` rejects an existing output folder during `--dry-run`.
- `safety-existing` protects a target workbook that already contains input data.
- `safety-lock` reports a target workbook with an Excel lock file and continues with other targets.

## How to get to it (user POV)

- Run the same direct CLI settlement with a source containing an unknown `WYKONAWCA`.
- Run `--dry-run` with a valid shared Placeholder and ensure the output folder
  is absent; an existing folder is a blocking error.
- Start with a worker template that already has data in `A18`.
- Leave `~$<template-name>.xlsx` beside a target as Excel does while it is open.
- Keep the placeholder named with no worker after the period separator.

## Driving it with PowerShell and run.py

Preconditions:

- Use the orchestrator's isolated variant for each safety proof.
- The locked variant runs the doctor before creating the lock file.

- **Unknown worker and placeholder.** Run the default `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`; the dry-run transcript records a sanitized mapping warning, `run.txt` records `BRAK_MAPOWANIA`, and `assert-run.txt` confirms the legacy placeholder has no input data.
- **Existing output folder.** `tests/test_cli_observability.py::test_cli_dry_run_rejects_existing_output_folder_without_changing_it` drives the public CLI with a synthetic pre-existing folder and verifies its sentinel is unchanged.
- **Existing data.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing`. The pre-existing target value remains, `NADPISANIE_ZABLOKOWANE` is recorded, and the process continues.
- **Excel lock.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked`. The output records `PLIK_ZABLOKOWANY` while Adrian can still be written.
- **Evidence.** Each command retains terminal output, exit codes, and read-only workbook assertions under its evidence directory. Do not log synthetic row values.

## Gotchas

- A missing mapping is a warning in the summary, not permission to infer a filename from similar text.
- A lock is represented by the exact `~$` filename; killing Excel or deleting a user-owned lock is not cleanup.
- Existing data includes real input cells but excludes the template formulas used for calculations.
- Safety variants are independent fixtures; do not stack them unless the expected result is explicitly recalculated.
