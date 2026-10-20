# Przygotowanie pliku zbiorczego

Dad prepares the Rozliczenie wewnętrzne and the Plik zbiorczy of a period
from Centrum: he picks the period (the last complete one is preselected),
looks at the plan without writing (`Podgląd bez zapisu`, DRY-RUN), confirms
the write (`Uruchom`, RUN) after a reminder to close the Rejestr zleceń, sees
the stages live over SSE, decides about an incomplete period in a dialog, and
gets the result: stops and warnings separately, each in three parts with the
terminal's content. Every Uruchomienie procesu appends to the CLI's metrics
file, and the history marks it as started from Centrum.

## Sub-features

- `przygotowanie-wybor-okresu`: the board row's next step opens Uruchomienia with the last complete period preselected, the files from the settings, and the reminder.
- `przygotowanie-podglad`: `Podgląd bez zapisu` on the `Następny krok` card, double-clicked, starts one DRY-RUN without an error toast, shows the plan (counts, warnings, Zlecenia na dzień, both file names), writes nothing, and appends one DRY-RUN metrics record.
- `przygotowanie-podglad-po-odswiezeniu`: after a reload, the confirmation of the previewed period has no no-preview warning, and a period without a successful preview still has it; `GET /api/runs/setup` marks `previewed` per period from the metrics history.
- `przygotowanie-potwierdzenie`: after a reload, `Uruchom` in the preview's result asks `Uruchomić z zapisem?` with the reminder and without the no-preview warning; its `Uruchom`, double-clicked while the dialog closes, starts one RUN without an error toast.
- `przygotowanie-decyzja`: an incomplete period waits in the decision dialog with Zlecenia na dzień and focus on `Przerwij bez zapisu`; the live counters behind it show the projection's `Ostrzeżenia`; a second Uruchomienie and closing Centrum are refused; the dialog survives a reload.
- `przygotowanie-przerwij`: `Przerwij bez zapisu` stops with the three-part message worded for Centrum and writes nothing.
- `przygotowanie-podwojne-klikniecie`: `Uruchom ponownie` double-clicked starts one RUN, `Kontynuuj` clicked three times while the stream lags sends one decision and its buttons wait for the stream, no error toast appears, and the result's `Folder okresu` double-clicked opens once.
- `przygotowanie-kontynuuj`: the RUN that `Uruchom ponownie` and `Kontynuuj` started in `przygotowanie-podwojne-klikniecie` finished OK with both period files published; metrics hold DRY-RUN OK, RUN BLAD_KRYTYCZNY, RUN OK, so the double clicks started no second Uruchomienie; the Centrum log has the start and end of each Uruchomienie.
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
- In `all` this feature runs after `metryki`, because it appends to the metrics files that Metryki counts.

- **Choose the period.** On Okresy click button `Przygotuj plik zbiorczy, okres 06_12_10_2026`. The URL ends in `#/uruchomienia`, combobox `Okres` shows `06_12_10_2026 · ostatni pełny`, group `Rejestr zleceń` shows the register's name, and `Zapisz i zamknij Rejestr zleceń w Excelu` is visible. `GET /api/runs/setup` (`api/przygotowanie-wybor-okresu.json`) preselects the token with `blocker: null`.
- **Preview.** Back on Okresy double-click region `Następny krok` → button `Podgląd bez zapisu`: one `POST /api/runs` (counted with `page.on("request")`) and no error toast in region `Notifications`. Region `Podgląd na żywo` shows `Podgląd gotowy · nic nie zapisano`, the warning (label `Ostrzeżenie`) starting `Ostatnie zlecenie okresu jest z soboty 10.10.2026`, list item `sob 10.10.2026: 1`, and the Plik zbiorczy name. `GET /api/runs/current` has the fixture's counts in `result.summary.figures` (`Zlecenia okresu`, `Zlecenia skuteczne`) and `result.summary.counts` (`Zlecenia na dzień`); `INEA/06_12_10_2026` does not exist; `/api/metrics` has one more Przygotowanie record, a DRY-RUN.
- **Preview remembered after a reload.** `page.reload()`, click `Nowe Uruchomienie procesu`, then `Uruchom` with `06_12_10_2026 · ostatni pełny` chosen: alertdialog `Uruchomić z zapisem?` has no `Nie było podglądu bez zapisu`. `Anuluj`, choose option `08_14_09_2026 · Brak plików okresu` in combobox `Okres`, click `Uruchom`: the dialog shows `Nie było podglądu bez zapisu`. `GET /api/runs/setup` (`api/przygotowanie-podglad-po-odswiezeniu.json`) has `previewed: true` only for the previewed period. Screenshot `39`. `Anuluj`.
- **Confirm.** `page.reload()` shows the finished preview again (Nowe Uruchomienie is the tab's own choice). Click `Uruchom` in the result banner. Alertdialog `Uruchomić z zapisem?` shows the reminder and no `Nie było podglądu bez zapisu`. Double-click its `Uruchom`: the second click lands while the dialog closes; one `POST /api/runs`, no error toast.
- **Decision.** Alertdialog `Kontynuować mimo niepełnego okresu?` shows the warning and list item `pon 12.10.2026: 0`; `Przerwij bez zapisu` is focused. `GET /api/runs/current` is `awaiting_decision`, and the counters strip (`dl[aria-label="Liczniki"]`) shows `Ostrzeżenia` equal to the preview's number of warnings. `POST /api/runs` with Centrum's `Origin` returns `409` (`api/przygotowanie-trwa-juz.json`), and so does `POST /api/shutdown` (`api/przygotowanie-zamkniecie-odmowa.json`). After `page.reload()` the dialog is still open.
- **Abort.** Click `Przerwij bez zapisu`. Label `Zatrzymanie` shows `Przerwano z powodu niepełnego okresu` and `Jeśli okres jest pełny, przy decyzji wybierz „Kontynuuj”.`; the result is `ending: stop` with headline `Zatrzymano` and one stop; nothing is on disk.
- **Double click.** Double-click `Uruchom ponownie`: the decision dialog returns after one `POST /api/runs`, with no error toast. Make the page report itself hidden (harness, labelled in `drive.txt`: the stream pauses, so its next view arrives late, as on Dad's laptop at CPU 6×, where the decision's answer comes before the stream's change). Click `Kontynuuj`, wait for the answer, then click it twice more (`force=True`): one `POST /api/runs/<id>/decision`, and `Kontynuuj` and `Przerwij bez zapisu` stay disabled; capture `3a`. Make the page visible again: the stream reconnects, the dialog closes on `Plik zbiorczy przygotowany`, and there is no error toast. Double-click the result's `Folder okresu`: one request and one line in `opened.jsonl`.
- **Continue.** No click of its own: `GET /api/runs/current` has the RUN from the double-click step finished with `result: OK`; both period files exist; the three newest Przygotowanie records are RUN OK, RUN BLAD_KRYTYCZNY, DRY-RUN OK, with no extra record from the double clicks; `<root>/logs/centrum-rozliczen.log` has `uruchomienie-start` and `uruchomienie-koniec … wynik=OK koniec=finished` lines without the row marker.
- **Status okresu.** On Okresy the row `06_12_10_2026` shows `Plik zbiorczy przygotowany` and `Następny krok` shows `Utwórz rozliczenia pracowników`.
- **Nienadpisywanie.** Open `#/uruchomienia`, click `Nowe Uruchomienie procesu`, `Uruchom`, and the dialog's `Uruchom`. Label `Zatrzymanie` shows `Plik tego okresu już istnieje, więc nie został nadpisany.`; both files keep their bytes.
- **History.** Click tab `Historia`. The newest row names `06_12_10_2026` without `.cmd`; the four newest `/api/metrics` runs have `origin: centrum`.
- **Proof.** Screenshots `30`–`39` and `3a`, `api/przygotowanie-*.json`, checks in `drive.txt`.

## Gotchas

- `Run.capture` waits for running animations, and a running stage's bar loops forever. Capture only in a settled state (finished, or waiting for the decision, when no stage runs).
- The Uruchomienie runs in the server's worker thread; wait on `/api/runs/current` (`finished_result` in `drive/common.py`), not on a fixed delay.
- Count metrics records through `/api/metrics`, not by lines: the fixture's Przygotowanie file ends with an invalid record, which the CLI's store cuts off on the next append.
- The no-preview warning follows the server: a period counts as previewed when the metrics history (Centrum or `.cmd`) has a DRY-RUN with result OK for it. The fixture's synthetic history already has such records for `15_21_09_2026`, `22_28_09_2026`, and `29_05_10_2026`, so use `08_14_09_2026` for the warning.
- The result toast appears only after a finished write and covers the bottom-right corner for a few seconds.
- `Uruchom` is also the confirmation dialog's button; scope the second click to the alertdialog.
- A repeated click is a no-op until the stream shows its effect, so the guarded buttons are disabled then: click them again with `force=True`, or Playwright waits for them to be enabled.
- The stream follows the tab's visibility (`watchRunEvents`); faking `document.visibilityState` pauses it without a reload. Always restore it (`finally`), or every later step sees a stale Uruchomienie.
