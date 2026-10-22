# Wskazanie folderów

On his first start Dad points Centrum to his folder okresów and Rejestr zleceń. Centrum's own process opens
Windows' file dialogs (tkinter, `_TkPlatform`), Dad picks the folder and the file, and the tab shows the Tablica
okresów and the Rejestr; both paths are kept in his settings file. From the Tablica okresów a period folder opens in
Explorer.

## Sub-features

- `folder-okresow`: button `Wskaż folder okresów` opens a `#32770` window `Wybierz folder okresów (np. Załączniki albo INEA)` owned by Centrum's process; the `INEA` path typed and confirmed closes it; table `Tablica okresów` has one row for each period folder of the fixture (`29_05_10_2026`, `22_28_09_2026`, `15_21_09_2026`; the last complete period follows today's date, so it is not checked); `config\centrum-ustawienia.yaml` has `folder_okresow` = that path (`api/ustawienia-folder.json`).
- `rejestr-zlecen`: button `Wskaż Rejestr zleceń` opens `Wybierz plik Rejestru zleceń`; the Rejestr's path typed and confirmed closes it; group `Rejestr zleceń` shows `ZLECENIA SYNTETYCZNE OD 01_01_2026.xlsx`; the settings file has `rejestr_zlecen` = that path (`api/ustawienia-rejestr.json`).
- `otwarcie-folderu`: button `Folder okresu, okres 15_21_09_2026` shows one toast `Otwieram` and opens a new Explorer window (`CabinetWClass`) whose title has `15_21_09_2026`; it closes with `WM_CLOSE`.

## How to get to it (user POV)

- Okresy on the first start: button `Wskaż folder okresów`; then `Wskaż Rejestr zleceń`.
- The settings card's buttons `Zmień …` open the same dialogs (not driven here; `verify-centrum-rozliczen` covers them with its scripted picker).
- Tablica okresów: a period's folder and file buttons.

## Driving it with the Windows harness

Preconditions:

- `start-skrotem` ran (Centrum from the shortcut, no settings file).

- **Folder okresów.** Open the URL; click button `Wskaż folder okresów` (exact). Wait for the dialog among the visible windows of the port owner's pid; capture the desktop (`folder-okresow-okno`). `answer_file_dialog(dialog, <INEA>)`: the path goes into the edit inside control `1148` with `WM_SETTEXT`, then button `1` gets `BM_CLICK`. The dialog must close within 5 s; if it is still open, the first confirm only opened the folder, so confirm once more with an empty name box (labelled `harness:`). Then check the table, the settings file and the API; capture `tablica-okresow`.
- **Rejestr zleceń.** Click button `Wskaż Rejestr zleceń` (exact) and answer `Wybierz plik Rejestru zleceń` with the Rejestr's path the same way. Check group `Rejestr zleceń`, the settings file and the API; capture `rejestr-zlecen`.
- **Explorer.** Note the open `CabinetWClass` windows; click button `Folder okresu, okres 15_21_09_2026` (exact). Region `Notifications` has one dialog `Otwieram` with `15_21_09_2026`; within 30 s a new Explorer window with that title appears; capture the desktop (`eksplorator`); close it.
- **Proof.** `pulpit/` `folder-okresow-okno`, `rejestr-zlecen-okno`, `eksplorator`; `screenshots/` `tablica-okresow`, `rejestr-zlecen`; `api/ustawienia-*.json`; `state/centrum-ustawienia.yaml`.

## Gotchas

- Only a folder is opened: the runner has no Excel, so opening an `.xlsx` there fails for a reason Dad never meets. Opening files in Excel stays covered by hand and by `verify-skoroszyty-w-excelu` on the Mac.
- The dialog belongs to Centrum's process, not to the browser: a window of the same title from another process is not Centrum's picker.
- Explorer's title is the folder's name, with ` - File Explorer` on Windows 11 and Server 2025, or the full path when Windows is set to show it; the check looks for the name anywhere in the title.
