# Otwarcie plików okresu

After Przygotowanie pliku zbiorczego, Dad opens the Rozliczenie wewnętrzne and
the Plik zbiorczy from the Folder okresu in Excel. Both open straight to the
sheet, with no repair question. The Plik zbiorczy links to the same Słownik as
its Wzorzec, every Wiersz danych has the Wzorzec's formulas with no error in
its amounts, and the Rejestr's Wyróżnienia show as they were.

## Sub-features

- `rozliczenie-wewnetrzne-bez-okna`: the Rozliczenie wewnętrzne opens in Excel with no dialog.
- `plik-zbiorczy-bez-okna`: the Plik zbiorczy opens in Excel with no dialog.
- `plik-zbiorczy-lacze`: Excel lists the same external workbook for the Plik zbiorczy as for the Wzorzec pliku zbiorczego.
- `plik-zbiorczy-formuly`: every Wiersz danych has the R1C1 formulas of `AU18:AY18` of the Wzorzec, and `AU:AX` shows no error.
- `plik-zbiorczy-ilosci`: Excel holds the Ilości usług Przygotowanie wrote from the Reguły ilości in `N:AP` of the four Zlecenia skuteczne (none for `prewencja`, only V and T for the unknown component), and the sums of row 15 of the Wzorzec count them.
- `plik-zbiorczy-wyroznienia`: ADRES of `PREP-SYN-ZL-2` is yellow with bold dark red text and WYKONAWCA of `PREP-SYN-ZL-4` is italic, as in the Rejestr.
- `plik-zbiorczy-wyglad-wiersza`: Excel auto-fits the Wiersze danych (Wygląd Wiersza danych, no stored height): every row with one line is exactly the sheet's standard height, and the row of `PREP-SYN-ZL-2`, whose CZYNNOŚCI ZREALIZOWANE has two lines, is taller.

## How to get to it (user POV)

- Centrum rozliczeń, Tablica okresów: the period's file links open the Rozliczenie wewnętrzne and the Plik zbiorczy in Excel.
- Finder: double click in `INEA\<okres>\` of the folder okresów.

## Driving it with AppleScript

Preconditions: the Baseline in `README.md`; both Wzorce were opened as the reference (step 4 of Drive).

- **Rozliczenie wewnętrzne.** Copy it to the desk; `excel.open_file` returns within the 180 s limit; `excel.close` removes `~$`. `STEP … rozliczenie-wewnetrzne-bez-okna | open_seconds=…`.
- **Plik zbiorczy.** Copy it to the desk and open it; it stays open for `gotowosc-w-excelu`.
- **Link.** `excel.link_names` equals the Wzorzec pliku zbiorczego's list (`links=1`).
- **Rows and formulas.** Headers of row 17 give `NUMER ZL.`, `ADRES`, `WYKONAWCA`; the four Zlecenia skuteczne are in rows 18–21. For each, `excel.formulas_r1c1("AU:AY")` equals the reference and `excel.error_cells("AU:AX")` is none.
- **Ilości usług.** `excel.read` of `N:AP` of each order's row gives exactly `QUANTITIES` of `run_excel_verification.py` as non-zero numbers, and `N15:AP15` their column sums (`cells=14 | sums_row=15`).
- **Wyróżnienia.** `excel.fill` of the two cells gives interior, font color, bold, italic: `(0xFFFF00, 0xC00000, True, False)` and `(0xFFFFFF, 0x000000, False, True)` (`cells=2`).
- **Wygląd Wiersza danych.** `excel.row_heights` of each order's row against `excel.standard_height`; `excel.shown_text` of DATA is remembered for `rozliczenia-pracownikow-w-excelu`. `STEP … plik-zbiorczy-wyglad-wiersza | rows=4 | one_line_pt=…`.

## Gotchas

- `AY` looks up the Słownik through the external link and shows `#N/D` without the Słownik on this Mac; only `AU:AX` must be free of errors.
- A Wzorzec whose external link no formula uses proves nothing: Excel drops such a link on save. The doctor rejects that fixture; the old synthetic Wzorce of `verify-rozliczenia` have exactly that.
- Dad's real Wzorce had wrapping in rows 18–31: before the Wygląd Wiersza danych (2026-10-22) Excel showed those rows 30 pt high instead of 14–15 pt. `string value` gives the text in the cell's number format but not the `#####` of a too narrow column, so the DATA check compares the number format's text, not the rendering.
- A repair dialog surfaces here as `ExcelDialog … not open` with `Excel dialogs: [...]`; `features/okno-naprawy.md` shows what it looks like.
