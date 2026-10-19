# Przygotowanie pliku zbiorczego

Dad prepares the Rozliczenie wewnętrzne and the Plik zbiorczy of a period
from Centrum: he picks the period (the last complete one is preselected),
looks at the plan without writing (`Podgląd bez zapisu`, DRY-RUN), confirms
the write (`Uruchom`, RUN) after a reminder to close the Rejestr zleceń, sees
the stages live over SSE, decides about an incomplete period in a dialog, and
gets the result: stops and warnings separately, each in three parts with the
terminal's lines. Every Uruchomienie procesu appends to the CLI's metrics
file, and the history marks it as started from Centrum.

## Sub-features

- `przygotowanie-wybor-okresu`: the board row's next step opens Uruchomienia with the last complete period preselected, the files from the settings, and the reminder.
- `przygotowanie-podglad`: `Podgląd bez zapisu` on the `Następny krok` card shows the plan (counts, warnings, Zlecenia na dzień, both file names), writes nothing, and appends one DRY-RUN metrics record.
- `przygotowanie-potwierdzenie`: `Uruchom` after a preview asks `Uruchomić z zapisem?` with the reminder and without the no-preview warning.
- `przygotowanie-decyzja`: an incomplete period waits in the decision dialog with Zlecenia na dzień and focus on `Przerwij bez zapisu`; a second Uruchomienie is refused; the dialog survives a reload.
- `przygotowanie-przerwij`: `Przerwij bez zapisu` stops with the three-part message worded for Centrum and writes nothing.
- `przygotowanie-kontynuuj`: `Uruchom ponownie`, then `Kontynuuj`, publishes both period files; metrics hold DRY-RUN OK, RUN BLAD_KRYTYCZNY, RUN OK.
- `przygotowanie-status-okresu`: the Tablica okresów shows `Plik zbiorczy przygotowany` and the next step moves on.
- `przygotowanie-nienadpisywanie`: a second RUN of the same period stops and leaves both files byte-identical.
- `przygotowanie-historia`: the `Historia` tab lists the four runs without the `.cmd` badge; `/api/metrics` marks them `centrum`.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Podgląd bez zapisu` (when the last complete period has no period files).
- Okresy → Tablica okresów → row button `Przygotuj plik zbiorczy, okres <token>` → Uruchomienia with that period chosen.
- Sidebar `Uruchomienia` (`#/uruchomienia`) → `Nowe Uruchomienie procesu`; tabs `Uruchomienie` and `Historia`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. The drive sets the folder okresów and the Rejestr zleceń through the native pickers if they are not set yet.
- The fixture's Rejestr zleceń has four orders in `06_12_10_2026`, the last on Saturday 10.10.2026 (`fixture.json` → `preparation`), and the Wzorzec pliku zbiorczego has no rows with zeros, so the plan carries two warnings.
- In `all` this feature runs last, because it appends to the metrics files that Metryki counts.

- **Choose the period.** On Okresy click button `Przygotuj plik zbiorczy, okres 06_12_10_2026`. The URL ends in `#/uruchomienia`, combobox `Okres` shows `06_12_10_2026 · ostatni pełny`, group `Rejestr zleceń` shows the register's name, and `Zapisz i zamknij Rejestr zleceń w Excelu` is visible. `GET /api/runs/setup` (`api/przygotowanie-wybor-okresu.json`) preselects the token with `blocker: null`.
- **Preview.** Back on Okresy click region `Następny krok` → button `Podgląd bez zapisu`. Region `Podgląd na żywo` shows `Podgląd gotowy · nic nie zapisano`, the warning (label `Ostrzeżenie`) starting `Ostatnie zlecenie okresu jest z soboty 10.10.2026`, list item `sob 10.10.2026: 1`, and the Plik zbiorczy name. `GET /api/runs/current` has the fixture's counts; `INEA/06_12_10_2026` does not exist; `/api/metrics` has one more Przygotowanie record, a DRY-RUN.
- **Confirm.** Click `Uruchom` in the result banner. Alertdialog `Uruchomić z zapisem?` shows the reminder and no `Nie było podglądu bez zapisu`. Click its `Uruchom`.
- **Decision.** Alertdialog `Kontynuować mimo niepełnego okresu?` shows the warning and list item `pon 12.10.2026: 0`; `Przerwij bez zapisu` is focused. `GET /api/runs/current` is `awaiting_decision`. `POST /api/runs` with Centrum's `Origin` returns `409` (`api/przygotowanie-trwa-juz.json`). After `page.reload()` the dialog is still open.
- **Abort.** Click `Przerwij bez zapisu`. Label `Zatrzymanie` shows `Przerwano z powodu niepełnego okresu` and `Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”.`; the result is `ending: stop`, `Status końcowy: ZATRZYMANO`; nothing is on disk.
- **Continue.** Click `Uruchom ponownie`, then `Kontynuuj`. Label `Wynik` shows `Plik zbiorczy przygotowany`; both period files exist; the three newest Przygotowanie records are RUN OK, RUN BLAD_KRYTYCZNY, DRY-RUN OK.
- **Status okresu.** On Okresy the row `06_12_10_2026` shows `Plik zbiorczy przygotowany` and `Następny krok` shows `Utwórz rozliczenia pracowników`.
- **Nienadpisywanie.** Open `#/uruchomienia`, click `Nowe Uruchomienie procesu`, `Uruchom`, and the dialog's `Uruchom`. Label `Zatrzymanie` shows `Plik tego okresu już istnieje, więc nie został nadpisany.`; both files keep their bytes.
- **History.** Click tab `Historia`. The newest row names `06_12_10_2026` without `.cmd`; the four newest `/api/metrics` runs have `origin: centrum`.
- **Proof.** Screenshots `30`–`38`, `api/przygotowanie-*.json`, checks in `drive.txt`.

## Gotchas

- `Run.capture` waits for running animations, and a running stage's bar loops forever. Capture only in a settled state (finished, or waiting for the decision, when no stage runs).
- The Uruchomienie runs in the server's worker thread; wait on `/api/runs/current` (`_finished_result`), not on a fixed delay.
- Count metrics records through `/api/metrics`, not by lines: the fixture's Przygotowanie file ends with an invalid record, which the CLI's store cuts off on the next append.
- The no-preview warning in the confirmation is per browser tab; after `page.goto` it shows again even though a preview ran earlier.
- The result toast appears only after a finished write and covers the bottom-right corner for a few seconds.
- `Uruchom` is also the confirmation dialog's button; scope the second click to the alertdialog.
