# Centrum rozliczeń verification map

This directory is the maintained source for verifying what Dad can do in
Centrum rozliczeń. Read this index before driving, then use the matching
feature file as the recipe.

## Baseline preconditions

- The built frontend in `src/rozliczenia/centrum/static/` matches `frontend/`
  (`npm run build` in `frontend/` after any frontend change).
- Playwright for Python and Chromium are installed, and on Windows `tzdata` (see `SKILL.md`, Launch).
- The computer may run in any time zone: a check of the screen counts dates in
  Dad's (`Europe/Warsaw`, the browser's), a check of the server's text in the computer's own.
- `run_centrum_verification.py` created a fresh run root with
  `create_centrum_fixture.py`, `serve_centrum.py` is serving it, and
  `centrum_doctor.py` reported `DOCTOR OK`.
- The fixture's "today" is Monday `2026-10-19`, so the last complete period is
  `06_12_10_2026`, whose Folder okresu does not exist. The folder okresów
  `INEA` holds `29_05_10_2026` (Plik zbiorczy przygotowany; its Plik zbiorczy
  has a Wykonawca missing from the konfiguracja wykonawców), `22_28_09_2026`
  (Rozliczenia pracowników gotowe, three files), `15_21_09_2026` (empty Folder
  okresu), and `Archiwum` (not a period).
- `<root>/Załączniki` holds Dad's layout for `uklad-folderow-taty`: weeks in
  `Rozliczenia 2026\{miesiąc}\INEA` of September, October, and November, with
  `06_12_10_2026` and `29_05_10_2026` prepared in October.
- `<root>/metrics/` holds both metrics files in the metrics schema: 18 valid
  synthetic Uruchomienia procesu (Przygotowanie pliku zbiorczego: 6 completed
  RUN, 1 RUN stopped in an old schema-1 record without its Rodzaj Zatrzymania,
  3 completed DRY-RUN; Przebieg rozliczeń: 5 completed RUN, one of them
  WYMAGA_SPRAWDZENIA, 1 RUN stopped „do Maksa” with `BLAD_NIEOCZEKIWANY`, 1 RUN
  stopped „dla taty” with `PLIK_ZBIORCZY_OTWARTY`, 1 DRY-RUN) and one record
  per file that the reader skips.
- The synthetic Rejestr zleceń has four orders in `06_12_10_2026`, the last on
  Saturday, so a RUN of Przygotowanie pliku zbiorczego asks about an
  incomplete period; its order cells carry the row marker.
  Centrum reads these, never the tool's own history.
- No settings are set when a run starts.
- Only for `wydajnosc`, the fixture is created with `--wariant rok-pracy`: `<root>/Rok pracy/Załączniki` holds 52 periods in Dad's layout and the metrics files hold a year of records (see `wydajnosc.md`).
- `<root>/aktualizacja/` holds the run's tool for `aktualizacja`: a clone (`klon`) on the first synthetic commit, with Dad's files in its `config/`, and a bare local "origin" (`origin.git`) one commit ahead that stops tracking his changed konfiguracja wykonawców, plus a branch `biblioteki` one commit later that needs a library pip cannot install offline and a branch `nie-startuje` whose Centrum does not start. Centrum's own commit is the clone's `HEAD`, and Aktualizacja narzędzia moves only this clone. The clone's `run_centrum.py` serves the run's scripted Centrum, so the Centrum the restart guardian starts after an update is again this run's.
- The run's `config/` holds a synthetic `worker_mapping.yaml` (three Wykonawcy)
  and the three Wzorce, valid for the engine's Sprawdzanie; Konfiguracja reads
  these, never Dad's `config/`.

## Driving conventions

- Drive through the browser with `drive_centrum.py`. Find elements by ARIA role
  and accessible name; the names are Polish UI text, so copy them exactly
  (`exact=True`: Playwright otherwise matches case-insensitive substrings, and
  `Wskaż folder okresów` differs from `Wskaż Folder okresów` only in case).
- Answer a native picker by writing the path to `<root>/picker/answer.txt`
  before the click. Leave the file absent to cancel.
- Read side effects from the run root: `config/centrum-ustawienia.yaml`,
  `dialogs.jsonl`, `opened.jsonl`, and `logs/uruchomienia/`.
- Change files on disk only inside the run root, and restore what a step moved.
- Capture with `Run.capture`, which waits for running transitions; a screenshot
  taken mid-transition shows content at partial opacity.

## Proof and skip reporting

- Every step records its action, the screen (`screenshots/`, `aria/`), the
  server's answer (`api/`), and the side effect on disk (`state/`, checks in
  `drive.txt`).
- Report a feature as verified only when its steps ran in this run. A feature
  left out with `--feature` is a skip; report it as one.
- `VERIFY FAIL` keeps `screenshots/zz-failure.png` and the evidence of every
  step before the failure.
- Evidence contains synthetic paths only; workbook content never appears.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible
behaviour, then exactly these H2s in order:

1. `Sub-features`: short IDs with one line each; the IDs match the
   `STEP <feature> | <id>` lines in `drive.txt`.
2. `How to get to it (user POV)`: every entry point Dad has.
3. `Driving it with Playwright for Python`: starts with `Preconditions:`, then
   labelled bullets pairing each action with the exact handle and the
   observable result.
4. `Gotchas`: traps that waste or invalidate a run.

When a slice adds a feature, add its file here, its module in `scripts/drive/` and an
entry in `drive_centrum.py`, and its screenshots in
`REQUIRED_SCREENSHOTS` of `run_centrum_verification.py`, in the same PR.

## Features

- [Ustawienia](./ustawienia.md) covers pointing to the folder okresów and the Rejestr zleceń through the native picker, one picker at a time (also for a double click), cancelling, a remembered path that is gone, and the remembered theme.
- [Układ folderów taty](./uklad-folderow-taty.md) covers pointing to `Załączniki` with weeks in `Rozliczenia {rok}\{miesiąc}\INEA`: weeks from every month on the board, Następny krok for the prepared last complete period, opening a file from its month folder, and restoring the flat folder.
- [Konfiguracja](./konfiguracja.md) covers the read-only view of the three Wzorce, the Wykonawcy from the konfiguracja wykonawców, and the tool version, with a Wzorzec open in Excel, a missing Wzorzec, a broken konfiguracja wykonawców, and proof that Centrum changes none of these files.
- [Tablica okresów](./tablica-okresow.md) covers the period list with Status okresu, the last complete period and Następny krok, opening period files and folders (once for a double or triple click), refreshing after changes on disk, and refusing foreign requests.
- [Aktualizacja narzędzia](./aktualizacja.md) covers the card `Narzędzie` on Konfiguracja with the run's synthetic tool clone and its local "origin": a newer version shown with the clone's commit and the card's button, which only a newer Wydanie brings, the Komunikat „brak połączenia z GitHubem” with `Wyślij do Maksa` and the clone unchanged without internet, then the card without its button once Konfiguracja has no answer from GitHub, the progress after a double click (the retry) that starts one update with a second update and closing refused and the card's button disabled too, Centrum closing itself and the tab waiting with `Ponowne uruchamianie Centrum…`, the tab reloading by itself on the new Centrum in the new commit with `Zaktualizowano`, the clone moved forward, Dad's files untouched and both commits in the log, the current tool without the button, `Masz najnowszą wersję.` when GitHub names a Wydanie the update does not take, gone once Centrum knows another newest Wydanie, `Instalowanie bibliotek…` followed by the Komunikat of a failed installation with the clone moved back, and a new version that does not start, after which the tab reloads on the old version with the Komunikat „Nowa wersja narzędzia nie wystartowała.”. It never reaches GitHub or PyPI.
- [Metryki](./metryki.md) covers the key numbers on Okresy, P50/P95 and the result distribution per process and mode, the stage-times chart and table, interrupted runs, the history table with sorting and filters, a record from outside Centrum appearing without a restart, and the empty state.
- [Przygotowanie pliku zbiorczego](./przygotowanie-pliku-zbiorczego.md) covers choosing the period, Podgląd bez zapisu (DRY-RUN) without writing, the confirmed RUN, the live stages, the incomplete-period decision (abort and continue, surviving a reload), refusing a second Uruchomienie, double clicks that start or decide once without an error toast, the three-part stop, Nienadpisywanie, the Status okresu afterwards, the records in the process's metrics file, and the Historia tab marking Centrum runs.
- [Przebieg rozliczeń](./przebieg-rozliczen.md) continues Dad's path from the Plik zbiorczy of Przygotowanie: Gotowość in Excel (simulated), choosing the period without a file, Podgląd bez zapisu with the plan per Wykonawca, the RUN confirmed as Gotowość with the live Szablony pracowników progress and closing refused, the Folder rozliczeń pracowników published at once, the Status okresu `Rozliczenia pracowników gotowe`, Nienadpisywanie, and a preview that needs checking.
- [Kontrola ilości](./kontrola-ilosci.md) covers the Kontrola ilości Centrum sends by itself after the RUN of Przebieg rozliczeń: waiting without a key in `config/zgloszenia/kolejka/` with nothing for Dad to see, tried again and kept at the next start without network, and sent at the start after that while Okresy is already shown, labelled `kontrola-ilosci`, with the queue emptied.
- [Diagnoza](./diagnoza.md) covers the kind of stop: a stop Dad fixes himself with `Uruchom ponownie`, the same Komunikat again offering `Diagnoza`, the read-only Diagnoza explaining the cause with `Uruchom ponownie` first and every check listed, a different Komunikat after the fix, a stop „do Maksa” offering `Diagnoza` at once (with a newer Wydanie only proposed under the confirmation), „Nie znalazłem przyczyny na tym komputerze” when every check of the files passes, the check `Klucz do Zgłoszeń` (missing or refused key) that never becomes the explanation, the Diagnoza added to the file of Logi of its Uruchomienie and queued as one more comment, and a nieoczekiwany wyjątek that the automatic Diagnoza hits too, leaving one check `nie sprawdzono` and `Wyślij do Maksa` working (the Zgłoszenie waits in the queue for the key).
- [Aktualność narzędzia i OneDrive](./aktualnosc-i-onedrive.md) covers the two Diagnoza checks beyond Dad's files with the scripted GitHub and OneDrive of `serve_centrum.py`: a newer Wydanie explaining the stop with `Zaktualizuj narzędzie` only when nothing else is wrong, no network leaving the freshness unchecked, no cause and no button, a Rejestr zleceń only in the cloud explaining „Zawsze zachowuj na tym urządzeniu”, the newer Wydanie next to it only as a quiet proposal with the same button second, that button disabled while its update runs, and both checks passing with no button.
- [Zgłoszenie](./zgloszenie.md) covers sending the Zgłoszenie to Maks from under the Diagnoza: the exact preview under `Co zostanie wysłane` with the line to the Logi of its Uruchomienie (queued, or the comment once sent), no key leaving it in the queue of the skrzynka with the card saying it waits for the key and Powiadomienia showing it, the key state on Konfiguracja (ready, missing, refused), the queued Zgłoszenie sending itself to the file skrzynka Zgłoszeń with the confirmation once the key is there and the clock moves, the confirmation after a reload, the same problem in the next Uruchomienie shown as already sent and waiting for the fix, a new Zgłoszenie linking the closed one, another problem offered for sending separately, and a Zgłoszenie sent without network waiting for the internet and sending itself once it is back.
- [Uwaga taty](./uwaga-taty.md) covers the header icon `Napisz do Maksa` on every page and its dialog: `Wyślij` disabled without a Tytuł, unbroken long text that wraps inside the dialog on a 1366×768 screen, the figure `Maks dostanie` equal to the server's draft, an Uwaga waiting in the skrzynka queue without a key with the calm `Wyślę do Maksa, gdy będzie internet.` and no Komunikat, and with the key a second Uwaga sent with `Uwaga wysłana do Maksa.` while the waiting one goes out in the same pass, both in the file skrzynka as `uwaga-taty` issues exactly as shown and both numbers in `config/uwagi-taty.json`. On a real Podgląd bez zapisu it covers the Uwaga pinned to an Uruchomienie: `Dotyczy` with `Ogólna` and `Do Uruchomienia`, the card's `Napisz do Maksa o tym Uruchomieniu` opening the dialog with that Uruchomienie checked in the server's list, the figure and the sent issue naming the Uruchomienie and leading to the first comment of its Logi in the skrzynka, and the same button only on Historia rows with a run id. When the skrzynka rejects the preview's Logi it covers the sent issue saying they did not arrive and, after Centrum starts again, its one comment with the link, and for Logi that never reached the queue the issue saying so.
- [Logi Uruchomienia](./logi-uruchomienia.md) covers the file of Logi in `logs/uruchomienia/` after every Uruchomienie procesu from Centrum: exactly one new file for a Podgląd bez zapisu (`podgląd`) and for a RUN that stops (`zapis`), each equal to its card with the codes of its Komunikaty, the Szablony pracowników of the written Przebieg rozliczeń with outcome and time, one file per Uruchomienie in the Centrum log, and no trace for Dad, no path and no workbook content. With a key, every file of Logi reaches the period's issue in the skrzynka Zgłoszeń as the newest comment of its Uruchomienie with a summary and the file's JSON, one more after each Diagnoza. In `all`, the files from before the restarts of `kontrola-ilosci` are still there.
- [Powiadomienia](./powiadomienia.md) covers the bell right of `Napisz do Maksa` on every page and the view Powiadomienia behind it, with no sidebar entry: the sent Uwaga taty and Zgłoszenie as Powiadomienia (the Zgłoszenie named by its „Co się stało”), Maks closing them as `completed` (`Rozwiązana. Będzie w następnej wersji.`) and `not_planned` (`Maks przeczytał.`) lighting the red dot, at most one question to the skrzynka per kind of case per 10 minutes, entering the view putting the dot out at once while the new rows keep their mark until Dad leaves, `config/powiadomienia.json` keeping them read, both themes, and no network passing silently with the last known state; and the Powiadomienie o nowej wersji: the newest Wydanie on `main` in its card above the list with its note, only the cases sent from this computer and `Zaktualizuj narzędzie`, which starts the update, an older Wydanie as a row, none from outside `main`, the card back in the list without the button once Dad is on that Wydanie, and no network for GitHub changing nothing.
- [Pomiar u taty](./pomiar-u-taty.md) covers the silent measurement: `Server-Timing` on every API answer, one `pomiar` entry in the Centrum log per cold start of each page and per menu click with the server time of every API request, no trace in the UI, no path or period token in the log, and a measurement from a foreign `Origin` refused.
- [Wydajność](./wydajnosc.md) measures Centrum on Dad's year of work in his laptop's CPU profiles (4× and 6×): cold start, reopening the tab, sidebar laps with the visible skeleton time (none in the second lap), interactions, API requests per scenario, bundle size, and CPU traces, against the baseline in `wydajnosc-baseline.json`. Only with `--feature wydajnosc`, never in `all`.
- [Start i zamykanie](./start-i-zamykanie.md) covers readiness, the second start that only opens the tab, the three-part message for a port held by another program, many tabs that keep working because a tab in the background gives back its connection, the Centrum log, and closing Centrum from the sidebar. It closes the server, so it runs last.
