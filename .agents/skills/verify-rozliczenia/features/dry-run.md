# Dry-run planning

Dry-run validates and previews the full set of worker workbooks without creating
the target folder or any output workbook. It reads the source, worker mapping,
and shared Placeholder; it only appends the existing local metrics record.

## Sub-features

- `dry-run-validation` checks the source name and location, destination absence,
  mapping shape, Placeholder workbook, source header, and worker identifiers.
- `dry-run-plan` lists the destination folder and one named output per configured
  worker, including workers with no source rows.
- `dry-run-no-write` leaves the source and Placeholder unchanged and creates no
  target folder.
- `dry-run-metrics` records a `DRY-RUN` telemetry entry without customer row
  contents or filesystem paths.

## How to get to it (user POV)

- Run `py -3 run.py --source <source> --config <mapping> --placeholder <placeholder> --metrics <metrics> --dry-run`.
- `--placeholder` defaults to `config/placeholder.xlsx`; supply the path to the
  shared Placeholder when it is stored elsewhere.
- The CMD and VBA launchers do not expose a dry-run flag; use the direct CLI.

## Driving it with PowerShell and run.py

Preconditions:

- Use a synthetic source, mapping, and Placeholder; the target folder must not
  exist before dry-run.
- The orchestrator creates unique fixture, evidence, and cleanup paths.

- **Run the user command.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The orchestrator records the real CLI transcript in `dry-run.txt`.
- **Check the plan and communication.** The assertion checks the period, target
  folder, each output filename, row counts, the empty worker, and a generic
  unknown-worker warning without echoing its identifier or row values.
- **Check no workbook write.** `assert-dry-run.txt` confirms the target folder
  was not created and source/Placeholder hashes still match the fixture manifest.
- **Check telemetry.** Read `metrics.jsonl`; the record keeps the existing
  schema and contains mode `DRY-RUN`, counters, and no source path or row data.

## Gotchas

- Dry-run reads the source and Placeholder and writes local metrics; it is not a
  zero-I/O simulation.
- An existing destination folder, invalid mapping, or missing/invalid
  Placeholder stops the CLI before any output workbook is created.
- An unmapped source identifier is reported without printing the identifier or
  row contents; the CLI returns a warning status after showing configured
  workers' plans.
- The default verification fixture intentionally contains an unmapped worker,
  so the dry-run and subsequent legacy write return semantic exit code `2`.
- A dry-run proves the preview path, not the later write path; the verifier
  creates legacy target templates only after asserting the dry-run result.
