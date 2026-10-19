# Dry-run planning

Dry-run validates and previews the full set of worker workbooks without creating
the target folder or any output workbook. It reads the source, worker mapping,
and shared Wzorzec rozliczenia pracownika, then appends a new local metrics record, creating the
metrics file and parent directory if needed.

## Sub-features

- `dry-run-validation` checks the source name and location, destination absence,
  mapping shape, Wzorzec rozliczenia pracownika workbook, source header, and worker identifiers.
- `dry-run-plan` lists the destination folder and one named output per configured
  worker, including workers with no source rows.
- `dry-run-no-write` leaves the source and Wzorzec rozliczenia pracownika unchanged and creates no
  target folder.
- `dry-run-metrics` records a `DRY-RUN` telemetry entry without customer row
  contents or filesystem paths.

## How to get to it (user POV)

- Run `py -3 run.py --source <source> --config <mapping> --worker-template <worker-template> --metrics <metrics> --dry-run`.
- `--worker-template` defaults to `config/Wzorzec rozliczenia pracownika.xlsx`; supply the path to the
  shared Wzorzec rozliczenia pracownika when it is stored elsewhere.
- `Utwórz rozliczenia.cmd` does not expose a dry-run flag; use the direct CLI.
  Centrum rozliczeń offers the same dry-run as `Podgląd bez zapisu`, which
  `verify-centrum-rozliczen` drives.

## Driving it with PowerShell and run.py

Preconditions:

- Use a synthetic source, mapping, and Wzorzec rozliczenia pracownika; the target folder must not
  exist before dry-run.
- The orchestrator creates unique fixture, evidence, and cleanup paths.

- **Run the CLI proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The orchestrator returns `0` after a successful proof; `--variant unmapped` records application exit `2` in `dry-run.txt` and checks the sanitized mapping warning.
- **Check the plan and communication.** The assertion checks the period, target
  folder, each output filename, row counts, the empty worker, and a generic
  unknown-worker warning without echoing its identifier or row values.
- **Check no workbook write.** `assert-dry-run.txt` confirms the target folder
  was not created and source/Wzorzec rozliczenia pracownika hashes still match the fixture manifest.
- **Check telemetry.** `assert-dry-run.txt` reports `metrics_safe=true`: exactly
  one completed `DRY-RUN` record (result `OK`, or `WYMAGA_SPRAWDZENIA` for
  `--variant unmapped`) with no row content or scratch path.

## Gotchas

- Dry-run reads the source and Wzorzec rozliczenia pracownika and writes local metrics; it is not a
  zero-I/O simulation.
- An existing destination folder, invalid mapping, or missing/invalid
  Wzorzec rozliczenia pracownika stops the CLI before any output workbook is created.
- An unmapped source identifier, or a Wiersz danych with an empty `WYKONAWCA`
  (`BRAK_WYKONAWCY`), is reported without printing the identifier or row
  contents; dry-run returns warning code `2` while showing the full plan.
- The default fixture has mapped workers only and returns `0`; use
  `--variant unmapped` to verify the warning path.
- A dry-run proves the preview path, not the later write path; the default
  verifier follows it with a real run through the same CLI.
