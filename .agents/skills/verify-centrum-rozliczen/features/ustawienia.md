# Ustawienia

Dad points Centrum once to his Rejestr zleceń and his folder okresów through
the native picker. Centrum remembers both, plus the light or dark theme, in a
local settings file outside git, and says plainly when a remembered path no
longer exists.

## Sub-features

- `ustawienia-pusty-stan`: with no settings file, Okresy asks for the folder okresów and nothing is set.
- `ustawienia-folder-okresow`: the folder picker sets the folder okresów, and Tablica okresów appears.
- `ustawienia-rejestr-zlecen`: the file picker sets the Rejestr zleceń; before that, Uruchomienia says it is missing for the start.
- `ustawienia-braki-do-startu`: back on Uruchomienia from the menu, the Rejestr zleceń is no longer missing: pointing it reads again what the start needs.
- `ustawienia-motyw-bez-odczytu`: switching the theme on Uruchomienia does not read again what the start needs: the theme is not one of Dad's files.
- `ustawienia-anulowanie`: a cancelled picker changes nothing.
- `ustawienia-nieistniejaca-sciezka`: a remembered Rejestr zleceń that is gone shows `Nie ma już: <name>`.
- `ustawienia-motyw`: the theme icon switches to light, and the choice survives a reload.

## How to get to it (user POV)

- Okresy with no folder okresów: the `Wskaż folder okresów` button in the empty state.
- Okresy, card `Ustawienia`: `Wskaż`/`Zmień` next to `Rejestr zleceń` and `Folder okresów`.
- Uruchomienia: the setup card has the same `Rejestr zleceń` and `Folder okresów` groups and buttons (for Przebieg rozliczeń, group `Plik zbiorczy` replaces the Rejestr); the drive uses Okresy.
- The sun/moon icon in the header (`Włącz motyw jasny` / `Włącz motyw ciemny`).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run and `DOCTOR OK`; no settings file exists yet.

- **Empty state.** Open the URL. The text `Wskaż folder okresów` is visible, and `GET /api/settings` returns `not_set` for both paths (`api/ustawienia-przed.json`).
- **Folder okresów.** Write the `INEA` path to `picker/answer.txt`, then click button `Wskaż folder okresów` (exact). Table `Tablica okresów` appears, the last line of `dialogs.jsonl` is `Wybierz folder okresów (np. Załączniki albo INEA)`, and the settings file contains the `INEA` path.
- **Rejestr zleceń.** Click link `Uruchomienia`: alert `Najpierw wskaż Rejestr zleceń.` is visible. Click link `Okresy`, write the Rejestr path, then click button `Wskaż Rejestr zleceń`. Group `Rejestr zleceń` shows `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, `dialogs.jsonl` ends with `Wybierz plik Rejestru zleceń`, and the settings file contains the path.
- **What the start needs.** Click link `Uruchomienia`. `Nowe Uruchomienie procesu` is shown without the alert `Najpierw wskaż Rejestr zleceń.`, button `Podgląd bez zapisu` is enabled, and `GET /api/runs/setup` (`api/ustawienia-braki-do-startu.json`) has no `blocker` for Przygotowanie pliku zbiorczego; capture `18`. Still there, click `Włącz motyw jasny`, then `Włącz motyw ciemny`, each until the settings file has the theme, and wait 400 ms: no `GET /api/runs/setup` is sent and `Podgląd bez zapisu` stays enabled (before #164 the second read came from remounting the start on every settings answer). Click link `Okresy`.
- **Cancel.** With no answer file, click button `Zmień Rejestr zleceń`. `dialogs.jsonl` gains one line, the button becomes enabled again, and the settings file is byte-identical.
- **Path gone.** Rename the Rejestr file, then reload. Group `Rejestr zleceń` shows `Nie ma już: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, and `GET /api/settings` reports `order_register.state` = `missing` (`api/ustawienia-brak-rejestru.json`). Rename it back.
- **Theme.** Click button `Włącz motyw jasny`. `<html>` loses class `dark` and the settings file gets `motyw: light`. After a reload the page is still light and the button reads `Włącz motyw ciemny`. Click it to return to dark.
- **Proof.** Screenshots `01`–`05` and `18`, and `state/centrum-ustawienia.yaml`.

## Gotchas

- `Wskaż folder okresów` (empty state) and `Wskaż Folder okresów` (settings card) differ only in case. Use `exact=True`.
- The picker request blocks until the picker answers. Write `answer.txt` before the click, never after.
- Centrum reads the remembered Rejestr zleceń only when Przygotowanie pliku zbiorczego runs; without it, starting that Uruchomienie is refused with `Najpierw wskaż …`.
- Settings reload when the tab regains focus, so a missing path can also appear without a manual reload.
