# Safety gates

Safety gates prevent a settlement from guessing a worker, modifying the shared
Wzorzec rozliczenia pracownika, overwriting an existing output folder, or publishing partial files.

## Sub-features

- `safety-unknown` warns in dry-run and prevents publication for an unmapped source worker.
- `safety-worker-template` validates and copies the shared Wzorzec rozliczenia pracownika without modifying it.
- `safety-target-folder` rejects an existing output folder without changing it.
- `safety-lock` rejects a Wzorzec rozliczenia pracownika with an Excel lock before creating output.
- `safety-rollback` removes staging files after a workbook processing failure.
- `safety-unreadable-source` stops on a damaged Plik zbiorczy with a safe Polish message and creates no output.
- `safety-worker-config` stops in Sprawdzanie on an unreadable, non-YAML, or invalid Konfiguracja wykonawców and creates no output.

## How to get to it (user POV)

- Run a dry-run and a real settlement with an unknown `WYKONAWCA`.
- Create the output folder before a run and place a sentinel inside.
- Leave `~$Wzorzec rozliczenia pracownika.xlsx` beside the shared Wzorzec rozliczenia pracownika as Excel does while it is open.
- Inject a failure while processing the second synthetic workbook and retry.
- Run against a Plik zbiorczy that is not a valid `.xlsx` (for example damaged).
- Run with a `worker_mapping.yaml` that is not valid YAML or breaks a Konfiguracja wykonawców rule.

## Driving it with PowerShell and the machine script

Preconditions:

- Use the orchestrator's isolated variant for each filesystem safety proof.
- The locked variant runs the doctor and dry-run before creating the Wzorzec rozliczenia pracownika lock.

- **Unknown worker.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped`. Dry-run warns with `BRAK_MAPOWANIA` and returns `2`; the real run stops with `NIEZNANY_WYKONAWCA`, returns `1`, and publishes no folder.
- **Untouched Wzorzec rozliczenia pracownika.** Every Przebieg rozliczeń variant's assertion (`default`, `existing`, `locked`, `unmapped`, `chain`) fails unless the Wzorzec rozliczenia pracownika `sha256` matches the fixture manifest. The `preparation` variants have no Wzorzec rozliczenia pracownika.
- **Existing output folder.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing`; the sentinel `existing-synthetic.txt` remains the only file and `run.json` stops with `FOLDER_ROZLICZEN_ISTNIEJE`.
- **Excel lock.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked`; the run returns `1`, stops with `ZLY_WZORZEC_PRACOWNIKA` whose "Co się stało" says the Wzorzec is open or locked, and creates no output.
- **Write failure.** Run `py -3 -m pytest tests/test_settlement_engine.py::test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion -q`; it checks cleanup and successful retry.
- **Unreadable Plik zbiorczy.** Run `py -3 -m pytest tests/test_settlement_engine.py -k nieczytelny -q`; the run stops in Odczyt danych with "Nie można odczytać Pliku zbiorczego …", no exception text and no output folder. The tests check the message, not the stage.
- **Broken Konfiguracja wykonawców.** No variant drives it. Create the default fixture with `create_fixture.py --root "$runRoot"`, overwrite `$runRoot\worker_mapping.yaml` with `workers: [unclosed`, run `py -3 tools\uruchom_proces.py settlement --source <fixture source> --config <mapping> --worker-template <wzorzec> --metrics <metrics>`, then run `cleanup.py --root "$runRoot"`. Expect exit `1`, stop `ZLA_KONFIGURACJA_WYKONAWCOW`, `Sprawdzanie` `failed` in `progress.phases`, and no `Rozliczenie pracowników` folder. `py -3 -m pytest tests/test_worker_config.py -q` covers the other reasons (unreadable file, not UTF-8, broken rule).
- **Evidence.** Each command retains its JSON result, exit code, metrics file, and read-only workbook assertions under its evidence directory. Do not log synthetic row values.

## Gotchas

- A missing mapping is a dry-run warning, but the real run does not publish an incomplete roster. A data row with an empty `WYKONAWCA` blocks the real run the same way (`BRAK_WYKONAWCY`).
- A lock is represented by the exact `~$` filename; do not kill Excel or delete a user-owned lock as cleanup.
- Workbooks are always copied from the common Wzorzec rozliczenia pracownika, not reused from a previous period.
- Safety variants are independent fixtures; do not stack them unless the expected result is explicitly recalculated.
