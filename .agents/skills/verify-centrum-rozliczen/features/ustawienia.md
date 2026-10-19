# Ustawienia

Dad points Centrum once to his Rejestr zleceń and his folder okresów through
the native picker. Centrum remembers both, plus the light or dark theme, in a
local settings file outside git, and says plainly when a remembered path no
longer exists.

## Sub-features

- `ustawienia-pusty-stan`: with no settings file, Okresy asks for the folder okresów and nothing is set.
- `ustawienia-folder-okresow`: the folder picker sets the folder okresów, and Tablica okresów appears.
- `ustawienia-rejestr-zlecen`: the file picker sets the Rejestr zleceń.
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
- **Folder okresów.** Write the `INEA` path to `picker/answer.txt`, then click button `Wskaż folder okresów` (exact). Table `Tablica okresów` appears, the last line of `dialogs.jsonl` is `Wybierz folder okresów (np. INEA)`, and the settings file contains the `INEA` path.
- **Rejestr zleceń.** Write the Rejestr path, then click button `Wskaż Rejestr zleceń`. Group `Rejestr zleceń` shows `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, `dialogs.jsonl` ends with `Wybierz plik Rejestru zleceń`, and the settings file contains the path.
- **Cancel.** With no answer file, click button `Zmień Rejestr zleceń`. `dialogs.jsonl` gains one line, the button becomes enabled again, and the settings file is byte-identical.
- **Path gone.** Rename the Rejestr file, then reload. Group `Rejestr zleceń` shows `Nie ma już: ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`, and `GET /api/settings` reports `order_register.state` = `missing` (`api/ustawienia-brak-rejestru.json`). Rename it back.
- **Theme.** Click button `Włącz motyw jasny`. `<html>` loses class `dark` and the settings file gets `motyw: light`. After a reload the page is still light and the button reads `Włącz motyw ciemny`. Click it to return to dark.
- **Proof.** Screenshots `01`–`05` and `state/centrum-ustawienia.yaml`.

## Gotchas

- `Wskaż folder okresów` (empty state) and `Wskaż Folder okresów` (settings card) differ only in case. Use `exact=True`.
- The picker request blocks until the picker answers. Write `answer.txt` before the click, never after.
- Centrum reads the remembered Rejestr zleceń only when Przygotowanie pliku zbiorczego runs; without it, starting that Uruchomienie is refused with `Najpierw wskaż …`.
- Settings reload when the tab regains focus, so a missing path can also appear without a manual reload.
