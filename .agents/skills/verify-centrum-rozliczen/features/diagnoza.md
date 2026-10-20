# Diagnoza

When an Uruchomienie procesu stops, Centrum tells Dad what kind of stop it is.
A stop Dad fixes himself („dla taty”) offers `Uruchom ponownie`, which starts
the same process for the same period in the same mode. A stop „do Maksa” (the
Komunikat tells him to pass it on, or an unexpected error) and the same
Komunikat coming back after `Uruchom ponownie` offer `Diagnoza` instead. The
Diagnoza checks Dad's computer read-only and explains the cause in three parts;
when Dad removes the cause himself, `Uruchom ponownie` comes first. The server
computes the kind of stop and the Diagnoza; the browser only shows them.

## Sub-features

- `diagnoza-dla-taty`: an Excel lock file next to the Rejestr zleceń stops a Podgląd bez zapisu with the three-part Komunikat, `stop_kind` `for_tata`, and only `Uruchom ponownie`.
- `diagnoza-powtorka`: `Uruchom ponownie` keeps the period and mode; the identical Komunikat is `repeated` and offers `Diagnoza` instead of `Uruchom ponownie`.
- `diagnoza-wyjasnienie`: `Diagnoza` finds the open Rejestr zleceń, the same Komunikat as the stop, so it says `Diagnoza potwierdza ten komunikat.` instead of repeating it and puts `Uruchom ponownie` on the banner (`next_action` `rerun`).
- `diagnoza-sprawdzono`: the collapsed list `Sprawdzono (10)` names every check in order with its result; the Diagnoza changed no file and left the lock file.
- `diagnoza-inny-komunikat`: after removing the lock, `Uruchom ponownie` ends with a different Komunikat (no orders in the period), which is `for_tata` again.
- `diagnoza-do-maksa`: a missing Wzorzec rozliczenia wewnętrznego is `for_maks` and offers `Diagnoza` at once; the Diagnoza confirms it and offers no `Uruchom ponownie`.
- `diagnoza-bez-przyczyny`: with the Wzorzec back, a reload and `Diagnoza` find no cause: the explanation banner `Wyjaśnienie Diagnozy` reads „Nie znalazłem przyczyny na tym komputerze. Wyślij do Maksa.”; the Centrum log records each Diagnoza with its cause code.

## How to get to it (user POV)

- Uruchomienia: a finished Uruchomienie procesu with a stop shows the three-part banner (`Zatrzymanie`) with `Uruchom ponownie` or `Diagnoza`.
- The Diagnoza result appears under the banner as region `Diagnoza`; a reload of the tab shows the stop again with `Diagnoza`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The period `08_14_09_2026` has no Folder okresu in any feature and the Rejestr zleceń has no orders in it, so no Uruchomienie of this feature writes a file.

- **Dla taty.** Create `~$<Rejestr zleceń name>` next to the Rejestr zleceń. On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose radio `Przygotowanie pliku zbiorczego` and option `08_14_09_2026 · Brak plików okresu` in combobox `Okres`, click `Podgląd bez zapisu` (exact). The `Zatrzymanie` banner in region `Podgląd na żywo` reads `Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku.` and holds button `Uruchom ponownie`; there is no `Diagnoza`. `GET /api/runs/current` has `stop_kind` `for_tata`.
- **Powtórka.** Click `Uruchom ponownie` in the banner. The server's view gets `stop_kind` `repeated` with the same period and `dry_run`; the banner now holds `Diagnoza` and no `Uruchom ponownie`.
- **Wyjaśnienie.** Click `Diagnoza` (it reads `Sprawdzam…` while the server checks). The explanation is the stop's own Komunikat, so region `Diagnoza` reads `Diagnoza potwierdza ten komunikat.` without a second banner, and the `Zatrzymanie` banner now holds `Uruchom ponownie`. The drive repeats `POST /api/runs/{id}/diagnosis` with Centrum's `Origin` (`api/diagnoza-wyjasnienie.json`): `next_action` `rerun`.
- **Sprawdzono.** Click `Sprawdzono (10)`. List `Sprawdzono` holds `Aktualność narzędzia`, `Ustawienia taty`, `Rejestr zleceń`, the two Wzorce of Przygotowanie, `Konfiguracja wykonawców`, `Folder okresu`, `Pliki okresu w Excelu`, `Pliki w OneDrive`, `Dziennik Centrum rozliczeń`, in order (the scripted GitHub and OneDrive of `serve_centrum.py` make the first and the ninth pass). The Rejestr zleceń, the Wzorce, and the konfiguracja wykonawców keep their bytes and `st_mtime_ns`, and the lock file still exists.
- **Inny Komunikat.** Delete the lock file, click `Uruchom ponownie` on the banner. The banner reads `W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu.` with `Uruchom ponownie`; `stop_kind` is `for_tata`; region `Diagnoza` is gone.
- **Do Maksa.** Rename `config/Wzorzec rozliczenia wewnętrznego.xlsx` aside, click `Uruchom ponownie`. The banner reads `Nie znaleziono wzorca, z którego powstają pliki okresu.` with `Diagnoza` at once (`stop_kind` `for_maks`). Click it: region `Diagnoza` confirms the Komunikat and no `Uruchom ponownie` is shown.
- **Bez przyczyny.** Rename the Wzorzec back, reload, click `Diagnoza`. The banner `Wyjaśnienie Diagnozy` in region `Diagnoza` reads `Nie znalazłem przyczyny na tym komputerze.` and `Wyślij do Maksa.`; the server's answer has every check `passed` and `next_action` `report`. The Centrum log has `diagnoza proces=preparation okres=08_14_09_2026 przyczyna=NIE_ZNALEZIONO_PRZYCZYNY`.
- **Proof.** Screenshots `50`–`57`, `api/diagnoza-*.json`, and the checks in `drive.txt`.

## Gotchas

- Use a period no other feature fills: in `all`, earlier features put period files into the empty Folder okresu `15_21_09_2026`.
- After `Uruchom ponownie` the identical banner text comes back; wait for the server's `stop_kind` `repeated`, not for the text, or the drive reads the previous Uruchomienie.
- The memory of the previous stop lives only in the server: restarting Centrum starts again from `Uruchom ponownie`. The HTTP API tests cover the restart; this drive does not restart Centrum.
- Restore the Wzorzec by renaming it back, never by copying: the no-change check compares modification times.
- A Diagnoza result lives only in the tab; a reload shows the stop with `Diagnoza` again, which the last step uses.
