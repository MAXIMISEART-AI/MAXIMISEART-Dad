# Diagnoza

When an Uruchomienie procesu stops, Centrum tells Dad what kind of stop it is.
A stop Dad fixes himself („dla taty”) offers `Uruchom ponownie`, which starts
the same process for the same period in the same mode. A stop „do Maksa” (the
Komunikat tells him to pass it on, or an ending the process did not stop
itself: an unexpected error or an error after the engine) and the same
Komunikat coming back after `Uruchom ponownie` offer `Diagnoza` instead; after
such an ending the Diagnoza starts by itself. The Diagnoza checks Dad's
computer read-only and explains the cause in three parts; when Dad removes the
cause himself, `Uruchom ponownie` comes first. The server computes the kind of
stop, whether and how to offer the Diagnoza (`diagnosis`: `on_request` or
`automatic`), and the Diagnoza; the browser only shows them. A check that
fails itself (a nieoczekiwany wyjątek inside the Diagnoza) is `nie sprawdzono`
in its place and the rest still runs, so the Diagnoza always ends with an
explanation and `Wyślij do Maksa`. Dad sees nothing more, but Centrum adds each
Diagnoza with a new result to the Logi Uruchomienia of its Uruchomienie: the
file gets the field `diagnosis`, and the queue of the skrzynka Zgłoszeń one more
comment with the whole Logi. The same explanation and every check with the
same state, code and (unless it passed) detail is the same result, whatever the
time, so the automatic Diagnoza at every showing of the card adds nothing.

## Sub-features

- `diagnoza-dla-taty`: an Excel lock file next to the Rejestr zleceń stops a Podgląd bez zapisu with the three-part Komunikat, `stop_kind` `for_tata`, and only `Uruchom ponownie`.
- `diagnoza-powtorka`: `Uruchom ponownie` keeps the period and mode; the identical Komunikat is `repeated` and offers `Diagnoza` instead of `Uruchom ponownie`.
- `diagnoza-wyjasnienie`: `Diagnoza` finds the open Rejestr zleceń, the same Komunikat as the stop, so it says `Diagnoza potwierdza ten komunikat.` instead of repeating it and puts `Uruchom ponownie` on the banner (`next_action` `rerun`); with the tool up to date there is no `Propozycja aktualizacji`.
- `diagnoza-sprawdzono`: the collapsed list `Sprawdzono (10)` names every check in order with its result; the Diagnoza changed no file and left the lock file.
- `diagnoza-inny-komunikat`: after removing the lock, `Uruchom ponownie` ends with a different Komunikat (no orders in the period), which is `for_tata` again.
- `diagnoza-do-maksa`: a missing Wzorzec rozliczenia wewnętrznego is `for_maks` and offers `Diagnoza` at once; with a newer Wydanie on `main` the Diagnoza still confirms the missing Wzorzec, offers no `Uruchom ponownie`, and only proposes the update in one quiet line `Jest też nowsza wersja narzędzia.` with an outline `Zaktualizuj narzędzie`, while `Wyślij do Maksa` stays the main action (`update_proposal`).
- `diagnoza-bez-przyczyny`: with the Wzorzec back, a reload and `Diagnoza` find no cause: the explanation banner `Wyjaśnienie Diagnozy` reads „Nie znalazłem przyczyny na tym komputerze. Wyślij do Maksa.”; the Centrum log records each Diagnoza with its cause code.
- `diagnoza-w-logach`: the file of Logi of that Uruchomienie (`logs/uruchomienia/*-<run id>.json`) holds the last Diagnoza in `diagnosis`: explanation code `NIE_ZNALEZIONO_PRZYCZYNY` and every check with the label, state and detail of the server's answer; without a key the newest `*-logi-uruchomienia-<first 8 of run id>.json` in `config/zgloszenia/kolejka/` holds that file character for character, after the queued Logi of the Uruchomienie itself.
- `diagnoza-nieoczekiwany-wyjatek`: a nieoczekiwany wyjątek while reading the Rejestr zleceń (`diagnosis` `automatic`) shows the Diagnoza, `Wyślij do Maksa` and `Co zostanie wysłane` without a click on `Diagnoza`; the same failure inside the Diagnoza leaves `Rejestr zleceń` `nie sprawdzono` and its type in the Centrum log and in the Zgłoszenie.
- `diagnoza-bez-powtorki`: a reload and Okresy → Uruchomienia show that Diagnoza again without a click, and the Centrum log has a Diagnoza for each, but no more Logi of that Uruchomienie wait in the queue: one for the Uruchomienie and one for its first Diagnoza.
- `diagnoza-nieoczekiwany-wyjatek-zgloszenie`: `Wyślij do Maksa` after that Diagnoza answers with the `Ostrzeżenie` „Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.” and `Spróbuj ponownie`; the preview waits in `config/zgloszenia/Zgłoszenie BLAD_NIEOCZEKIWANY 08_14_09_2026.md`.

## How to get to it (user POV)

- Uruchomienia: a finished Uruchomienie procesu with a stop shows the three-part banner (`Zatrzymanie`) with `Uruchom ponownie` or `Diagnoza`.
- The Diagnoza result appears under the banner as region `Diagnoza`; a reload of the tab shows the stop again with `Diagnoza`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The period `08_14_09_2026` has no Folder okresu in any feature and the Rejestr zleceń has no orders in it, so no Uruchomienie of this feature writes a file.

- **Dla taty.** Create `~$<Rejestr zleceń name>` next to the Rejestr zleceń. On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose radio `Przygotowanie pliku zbiorczego` and option `08_14_09_2026 · Brak plików okresu` in combobox `Okres`, click `Podgląd bez zapisu` (exact). The `Zatrzymanie` banner in region `Podgląd na żywo` reads `Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku.` and holds button `Uruchom ponownie`; there is no `Diagnoza`. `GET /api/runs/current` has `stop_kind` `for_tata`.
- **Powtórka.** Click `Uruchom ponownie` in the banner. The server's view gets `stop_kind` `repeated` with the same period and `dry_run`; the banner now holds `Diagnoza` and no `Uruchom ponownie`.
- **Wyjaśnienie.** Click `Diagnoza` (it reads `Sprawdzam…` while the server checks). The explanation is the stop's own Komunikat, so region `Diagnoza` reads `Diagnoza potwierdza ten komunikat.` without a second banner, and the `Zatrzymanie` banner now holds `Uruchom ponownie`. There is no note `Propozycja aktualizacji`. The drive repeats `POST /api/runs/{id}/diagnosis` with Centrum's `Origin` (`api/diagnoza-wyjasnienie.json`): `next_action` `rerun`, `update_proposal` `false`.
- **Sprawdzono.** Click `Sprawdzono (10)`. List `Sprawdzono` holds `Ustawienia taty`, `Pliki w OneDrive`, `Rejestr zleceń`, the two Wzorce of Przygotowanie, `Konfiguracja wykonawców`, `Folder okresu`, `Pliki okresu w Excelu`, `Aktualność narzędzia`, `Dziennik Centrum rozliczeń`, in order (the scripted GitHub and OneDrive of `serve_centrum.py` make `Aktualność narzędzia` and `Pliki w OneDrive` pass). The Rejestr zleceń, the Wzorce, and the konfiguracja wykonawców keep their bytes and `st_mtime_ns`, and the lock file still exists.
- **Inny Komunikat.** Delete the lock file, click `Uruchom ponownie` on the banner. The banner reads `W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu.` with `Uruchom ponownie`; `stop_kind` is `for_tata`; region `Diagnoza` is gone.
- **Do Maksa.** Rename `config/Wzorzec rozliczenia wewnętrznego.xlsx` aside, click `Uruchom ponownie`. The banner reads `Nie znaleziono wzorca, z którego powstają pliki okresu.` with `Diagnoza` at once (`stop_kind` `for_maks`). Write 40 × `e` to `<root>/github/main-commit.txt` and click `Diagnoza`: region `Diagnoza` confirms the Komunikat, note `Propozycja aktualizacji` reads `Jest też nowsza wersja narzędzia.` and holds button `Zaktualizuj narzędzie` (enabled, outline) while `Wyślij do Maksa` is primary, and no `Uruchom ponownie` is shown. The answer (`api/diagnoza-do-maksa-wyjasnienie.json`) has `confirms_stop` `true`, `next_action` `report`, and `update_proposal` `true`. Delete `main-commit.txt`.
- **Bez przyczyny.** Rename the Wzorzec back, reload, click `Diagnoza`. The banner `Wyjaśnienie Diagnozy` in region `Diagnoza` reads `Nie znalazłem przyczyny na tym komputerze.` and `Wyślij do Maksa.`; the server's answer has every check `passed` and `next_action` `report`. The Centrum log has `diagnoza proces=preparation okres=08_14_09_2026 przyczyna=NIE_ZNALEZIONO_PRZYCZYNY`.
- **W Logach.** Read the file of Logi of that `run.id` and the queue as in `diagnoza-w-logach`. Nothing on the page changes; the checks are in `drive.txt`.
- **Nieoczekiwany wyjątek.** Create `<root>/awaria/odczyt-rejestru` (the fault hook of `serve_centrum.py`; it reaches the process and the Diagnoza alike), click `Nowe Uruchomienie procesu` and start the same Podgląd bez zapisu. Without any click, while the hook file still exists, region `Diagnoza` shows `Wyjaśnienie Diagnozy` with `Nie znalazłem przyczyny na tym komputerze.`, button `Wyślij do Maksa` and the collapsed `Co zostanie wysłane`; the banner has no `Diagnoza` button. The server's result has `ending` `unexpected` and `diagnosis` `automatic`. In `Sprawdzono (10)` the item `Rejestr zleceń` reads `Nie udało się sprawdzić: nieoczekiwany błąd.` with the icon `nie sprawdzono`. The Centrum log has `nieoczekiwany-wyjatek typ=RuntimeError miejsce="Diagnoza: Rejestr zleceń"` and no exception text; figure `Treść Zgłoszenia` under `Co zostanie wysłane` has the title `BLAD_NIEOCZEKIWANY: …` and that log entry.
- **Bez powtórki.** With the hook file still there, note the queued `*-logi-uruchomienia-<first 8 of run id>.json` of that Uruchomienie (two) and the `diagnoza proces=preparation okres=08_14_09_2026` lines of the Centrum log. Reload: region `Diagnoza` shows `Nie znalazłem przyczyny na tym komputerze.` again without a click. Click link `Okresy` (heading `Okresy`), then link `Uruchomienia`: the same. The log has two more `diagnoza` lines; the queue has the same two files. Open `Co zostanie wysłane` again: the next step compares with this preview. Delete the hook file.
- **Zgłoszenie po wyjątku.** Without `config/zgloszenia-klucz.txt`, click `Wyślij do Maksa` in region `Diagnoza`. Label `Ostrzeżenie` reads „Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.” with button `Spróbuj ponownie`; `config/zgloszenia/Zgłoszenie BLAD_NIEOCZEKIWANY 08_14_09_2026.md` is `# <title>\n\n<body>` as shown, and the server's result has `report` `saved`.
- **Proof.** Screenshots `50`–`59`, `api/diagnoza-*.json`, and the checks in `drive.txt`.

## Gotchas

- Use a period no other feature fills: in `all`, earlier features put period files into the empty Folder okresu `15_21_09_2026`.
- After `Uruchom ponownie` the identical banner text comes back; wait for the server's `stop_kind` `repeated`, not for the text, or the drive reads the previous Uruchomienie.
- The memory of the previous stop lives only in the server: restarting Centrum starts again from `Uruchom ponownie`. The HTTP API tests cover the restart; this drive does not restart Centrum.
- Restore the Wzorzec by renaming it back, never by copying: the no-change check compares modification times.
- Delete `<root>/github/main-commit.txt` after the `Do Maksa` step: with a newer Wydanie on `main` and no other cause, `Bez przyczyny` would read `Jest nowsza wersja narzędzia.`
- A Diagnoza result lives only in the tab; a reload shows the stop with `Diagnoza` again, which the `Bez przyczyny` step uses. An automatic Diagnoza (after a nieoczekiwany wyjątek) instead runs again by itself on every load of the card; a run with the same result as the last one queues no more Logi, a new result queues one more comment (`Bez powtórki`).
- Keep the fault hook file during `Bez powtórki`: without it the Rejestr zleceń passes, which is a new result and rightly one more queued Logi.
- Keep the fault hook file until the automatic Diagnoza is shown: deleting it right after the start lets the Diagnoza read the Rejestr zleceń and hides a Diagnoza that breaks on the same failure.
- Compare the saved Zgłoszenie with the preview in the tab; an extra `POST /api/runs/{id}/diagnosis` from the drive would replace the preview the button sends.
