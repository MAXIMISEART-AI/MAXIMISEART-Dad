# Safety gates

Safety gates prevent a settlement from guessing a worker, modifying the shared
Placeholder, overwriting an existing output folder, or publishing partial files.

## Sub-features

- `safety-unknown` warns in dry-run and prevents publication for an unmapped source worker.
- `safety-placeholder` validates and copies the shared Placeholder without modifying it.
- `safety-target-folder` rejects an existing output folder without changing it.
- `safety-lock` rejects a Placeholder with an Excel lock before creating output.
- `safety-rollback` removes staging files after a workbook processing failure.

## How to get to it (user POV)

- Run a dry-run and a real CLI settlement with an unknown `WYKONAWCA`.
- Create the output folder before a run and place a sentinel inside.
- Leave `~$placeholder.xlsx` beside the shared Placeholder as Excel does while it is open.
- Inject a failure while processing the second synthetic workbook and retry.

## Driving it with PowerShell and run.py

Preconditions:

- Use the orchestrator's isolated variant for each filesystem safety proof.
- The locked variant runs the doctor and dry-run before creating the Placeholder lock.

- **Unknown worker.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped`. Dry-run warns; the real run returns `1` and publishes no folder.
- **Existing output folder.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing`; the sentinel remains the only file.
- **Excel lock.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked`; the run returns `1` and creates no output.
- **Write failure.** Run `py -3 -m pytest tests/test_settlement_engine.py::test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion -q`; it checks cleanup and successful retry.
- **Evidence.** Each command retains terminal output, exit codes, and read-only workbook assertions under its evidence directory. Do not log synthetic row values.

## Gotchas

- A missing mapping is a dry-run warning, but the real run does not publish an incomplete roster.
- A lock is represented by the exact `~$` filename; do not kill Excel or delete a user-owned lock as cleanup.
- Workbooks are always copied from the common Placeholder, not reused from a previous period.
- Safety variants are independent fixtures; do not stack them unless the expected result is explicitly recalculated.
