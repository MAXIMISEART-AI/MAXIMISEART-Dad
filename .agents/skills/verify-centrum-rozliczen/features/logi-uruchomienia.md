# Logi Uruchomienia

After every Uruchomienie procesu Dad starts in Centrum, Centrum writes one JSON
file of Logi Uruchomienia to `logs/uruchomienia/` next to its log (ADR 0015),
whatever the mode, result and ending. The file says whether it was a `podgląd`
or a `zapis`, carries the card's result, ending, Rodzaj Zatrzymania, summary and
Komunikaty in three parts with their codes, the Szablony pracowników with their
outcome and time, the tool's commit, and the process's files by name. Dad sees
nothing of it: no alert, toast or text on the card. No path and no workbook
content reach the file.

## Sub-features

- `logi-podglad`: a Podgląd bez zapisu of Przebieg rozliczeń for `29_05_10_2026` adds exactly one file with `mode: "podgląd"`; `run_id`, `result`, `ending`, `stop_kind`, `summary` and `notices` equal the card, and its one message is the card's warning in three parts with kind `warning` and code `BRAK_MAPOWANIA`.
- `logi-zatrzymanie`: a RUN of the same period stops „dla taty” and adds exactly one file with `mode: "zapis"`, equal to the card, whose one message is the card's Zatrzymanie with kind `stop` and code `NIEZNANY_WYKONAWCA`.
- `logi-szablony`: the file of the written Przebieg rozliczeń of `06_12_10_2026` (the card `przebieg-rozliczen` recorded) lists every Wykonawca in order with outcome `ZAPISANO`, its rows and its time; the first Szablon pracownika, paced by the harness, took at least the pacing.
- `logi-kazde-uruchomienie`: every `uruchomienie-koniec` line of the Centrum log has exactly one file with the same process, mode, period, result and ending, in the same order, and no Uruchomienie has two.
- `logi-bez-sladu`: Uruchomienia, also after a reload, shows nothing about the Logi; no file holds a path in the run root or the fixture's row marker; the process's files are names only.

## How to get to it (user POV)

- None: Dad starts Uruchomienia procesu as always. Maks reads the files in `logs/uruchomienia/` on Dad's computer.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- `przebieg-rozliczen` ran in this run (`api/przebieg-zapisane.json` exists). Run alone (`--feature logi-uruchomienia`), the drive runs it first, with its Przygotowanie pliku zbiorczego.
- `INEA/29_05_10_2026` still has Status okresu `Plik zbiorczy przygotowany`, with a Wykonawca the konfiguracja wykonawców does not know (`fixture.json` → `settlement.needs_check`).

- **Files of Logi.** The drive reads `<root>/logs/uruchomienia/*.json` before and after each Uruchomienie; exactly one name is new.
- **Preview.** `#/uruchomienia` → button `Nowe Uruchomienie procesu` → radio `Przebieg rozliczeń` (combobox `Okres` shows `29_05_10_2026`) → button `Podgląd bez zapisu`. Label `Wynik` shows `Podgląd wymaga sprawdzenia · nic nie zapisano`; `GET /api/runs/current` is `api/logi-podglad.json`. The new file has the card's `run.id`, `process`, `period`, `mode: "podgląd"`, the result's `result`, `ending`, `stop_kind`, `summary`, `notices`, its `stops` then `warnings` as `messages` (`kind` `stop`/`warning`, the same `what`, `where`, `action`), codes `[warning BRAK_MAPOWANIA]`, and `tool` `{"wydanie": null, "commit": <the commit Centrum runs>}`. The page text has no `Logi`, `Logów`, `Logach`, `Logami` or `uruchomienia/`. Capture `160`.
- **Zatrzymanie.** The same choice, then button `Uruchom` and the alertdialog `Uruchomić z zapisem?` → `Uruchom`. Label `Zatrzymanie` shows `W Pliku zbiorczym jest WYKONAWCA`; `api/logi-zatrzymanie.json`. The new file equals the card with `mode: "zapis"`, codes `[stop NIEZNANY_WYKONAWCA]`, and the same `tool`. Capture `161`.
- **Szablony pracowników.** The file whose `run_id` is the `run.id` of `api/przebieg-zapisane.json` equals that card (its `tool` aside) and has `templates` `[(wykonawca, "ZAPISANO", rows)]` for `fixture.json` → `workers` and `settlement.rows_per_worker`, each with an integer `duration_ms`, the first ≥ the Szablony pacing of `przebieg-rozliczen` (1500 ms).
- **Every Uruchomienie.** The `uruchomienie-koniec` lines of `logs/centrum-rozliczen.log` (`tryb` `DRY-RUN` is `podgląd`, `RUN` is `zapis`) equal the files sorted by `started_at`, and every `run_id` is unique. In `all` this covers every Uruchomienie of the run, with the unexpected exceptions of `diagnoza`.
- **No trace.** Reload `#/uruchomienia`: label `Zatrzymanie` is visible and the page text says nothing about the Logi. No file contains the run root or `CENTRUM-SYN-ROW`; every `environment.files[].name` has no `/` or `\`.
- **Proof.** Screenshots `160`–`161`, `api/logi-*.json`, `state/uruchomienia/` (every file of Logi of the run, also checked by the self-test's evidence hygiene), checks in `drive.txt`.

## Gotchas

- The files are written before the card shows the result, so read them after the card is finished; a file read while the Uruchomienie runs is not there yet.
- File names start with the start time in whole seconds; sort by `started_at` inside the file, not by name, when two Uruchomienia start in the same second.
- The card's Komunikaty have no code; only the file has it, so the drive checks codes against the messages it knows for these runs.
- Logi surviving a restart of Centrum is proved only in `all`: `kontrola-ilosci` restarts Centrum twice after Przebieg rozliczeń, so `logi-kazde-uruchomienie` finds the files of the Uruchomienia before those restarts. Alone, the feature does not restart; `tests/test_centrum_logi_uruchomienia.py` covers it over HTTP.
- `tool.commit` is the commit Centrum ran when the Uruchomienie ended. In `all`, `powiadomienie-o-naprawie` pins another one (`github/tool-commit.txt`) after `przebieg-rozliczen`, so only the drive's own Uruchomienia are compared with `served_version`, and never with the clone's `HEAD`.
