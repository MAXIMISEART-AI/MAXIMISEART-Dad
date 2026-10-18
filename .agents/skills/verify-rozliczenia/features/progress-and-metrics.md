# Progress and telemetry

The terminal dashboard gives the user phase progress, per-template results,
semantic status, and safe local timing history. The CLI process returns an exit
code separately from the displayed status.

## Sub-features

- `progress-phases` reports `Sprawdzanie`, `Odczyt danych`, `Planowanie`, and `Zapisywanie` in order.
- `progress-templates` reaches `3/3 (100%)` and reports per-template statuses.
- `progress-status` distinguishes an operational warning exit (`2`) from a critical failure exit (`1`).
- `metrics-safe` appends local JSONL telemetry without customer row contents or source paths.

## How to get to it (user POV)

- Dad runs `Utwórz rozliczenia.cmd` from a terminal or passes it a source file.
- Direct `py -3 run.py` calls are for verification with explicit source and metrics paths.

## Driving it with PowerShell and run.py

Preconditions:

- Run the one-command orchestrator from the repository root.
- Its UTF-8 evidence files retain plain CLI output; do not rely on a Rich live screen that disappears at process exit.

- **Check ordered phases and template progress.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. `assert-run.txt` reports `progress_reported=true`: `run.txt` shows `Etap: Sprawdzanie`, `Odczyt danych`, `Planowanie`, `Zapisywanie` in order, `Postęp szablonów: 3/3 (100%)`, two `ZAPISANO` and one `PUSTY_SZABLON` lines, and `Status semantyczny: OK`.
- **Check semantic exit.** The default fixture records application exit `0` and `Status semantyczny: OK`. The `unmapped` variant returns `2` for dry-run and `1` for the real run, which stops before publication.
- **Check metrics.** `assert-run.txt` reports `metrics_safe=true`: the history holds a completed `DRY-RUN` then `RUN` record, both `OK`, with no row content or scratch path. Each record has `schema_version`, `started_at`, `mode`, `period`, `completed`, `result`, `phase_durations_ms`, `total_duration_ms`, and `counters`; the copy stays in the evidence as `metrics.jsonl`.
- **Check repeated-run statistics.** The current run counts, so `Statystyki DRY-RUN`, `P50`, and `P95` appear once five comparable completed records exist. Both processes share this through Uruchomienie procesu (`process_run`); prove it with `py -3 -m pytest tests/test_process_run.py::test_statistics_report_both_modes_and_every_phase -q`.

## Gotchas

- Redirected output uses the plain adapter; the Rich dashboard is not stable evidence by itself.
- An unmapped worker is a dry-run warning and a critical real-run failure; other workbooks are never published without a complete mapping.
- Metrics are observability only; failure to append them must not be mistaken for a settlement failure.
- Never capture workbook row contents or customer-identifying paths in a transcript.
