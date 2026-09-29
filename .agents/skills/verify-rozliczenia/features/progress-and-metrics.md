# Progress and telemetry

The terminal dashboard gives the user phase progress, per-template results,
semantic status, exit code, and safe local timing history for a settlement run.

## Sub-features

- `progress-phases` reports `Sprawdzanie`, `Odczyt danych`, `Planowanie`, and `Zapisywanie` in order.
- `progress-templates` reaches `3/3 (100%)` and reports per-template statuses.
- `progress-status` distinguishes an operational warning exit (`2`) from a critical failure exit (`1`).
- `metrics-safe` appends local JSONL telemetry without customer row contents or source paths.
- `vba-no-observer` runs the same engine without a CLI progress observer; completed phase timings come from `SettlementSummary`.

## How to get to it (user POV)

- Run `py -3 run.py` from a terminal with a source path and metrics path.
- Run `Utwórz rozliczenia.cmd` from a terminal or by choosing a source in its file dialog.
- Run the Excel button `UruchomRozliczenia`; it waits for the same engine and reports its exit result without attaching a progress observer.

## Driving it with PowerShell and run.py

Preconditions:

- Run the one-command orchestrator from the repository root.
- Its UTF-8 evidence files retain plain CLI output; do not rely on a Rich live screen that disappears at process exit.

- **Check ordered phases.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py` and assert the first occurrences in `run.txt` are `Sprawdzanie`, `Odczyt danych`, `Planowanie`, then `Zapisywanie`.
- **Check template progress.** Assert `Postęp szablonów: 3/3 (100%)`, `Liczniki:`, and the per-template status lines in `run.txt`.
- **Check semantic exit.** The default fixture records application exit `0` and `Status semantyczny: OK`. The `unmapped` variant returns `2` for dry-run and `1` for the real run, which stops before publication.
- **Check metrics.** Read the copied evidence file `metrics.jsonl` as JSONL. It contains `mode`, `period`, `completed`, `result`, phase durations, and counters; it must not contain a full source path, address, order number, or row text.
- **Check observer-free launcher.** Run `py -3 -m pytest tests/test_cmd_launcher.py -k without_a_progress_observer` on Windows. This drives CMD with the VBA flag and checks workbook writes; it does not drive desktop Excel.
- **Check repeated-run statistics.** After five comparable dry-runs, a sixth dry-run prints `Statystyki DRY-RUN`, `P50`, and `P95`. Use a fresh metrics file for this test and retain the output as evidence.

## Gotchas

- Redirected output uses the plain adapter; the Rich dashboard is not stable evidence by itself.
- An unmapped worker is a dry-run warning and a critical real-run failure; other workbooks are never published without a complete mapping.
- Metrics are observability only; failure to append them must not be mistaken for a settlement failure.
- Never capture workbook row contents or customer-identifying paths in a transcript.
