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
- `plik-zbiorczy-wyroznienia`: ADRES of `PREP-SYN-ZL-2` is yellow with bold dark red text and WYKONAWCA of `PREP-SYN-ZL-4` is italic, as in the Rejestr.

## How to get to it (user POV)

- Centrum rozliczeń, Tablica okresów: the period's file links open the Rozliczenie wewnętrzne and the Plik zbiorczy in Excel.
- Finder: double click in `INEA\<okres>\` of the folder okresów.

## Driving it with AppleScript

Preconditions: the Baseline in `README.md`; both Wzorce were opened as the reference (step 4 of Drive).

- **Rozliczenie wewnętrzne.** Copy it to the desk; `excel.open_file` returns within the 180 s limit; `excel.close` removes `~$`. `STEP … rozliczenie-wewnetrzne-bez-okna | open_seconds=…`.
- **Plik zbiorczy.** Copy it to the desk and open it; it stays open for `gotowosc-w-excelu`.
- **Link.** `excel.link_names` equals the Wzorzec pliku zbiorczego's list (`links=1`).
- **Rows and formulas.** Headers of row 17 give `NUMER ZL.`, `ADRES`, `WYKONAWCA`; the four Zlecenia skuteczne are in rows 18–21. For each, `excel.formulas_r1c1("AU:AY")` equals the reference and `excel.error_cells("AU:AX")` is none.
- **Wyróżnienia.** `excel.fill` of the two cells gives interior, font color, bold, italic: `(0xFFFF00, 0xC00000, True, False)` and `(0xFFFFFF, 0x000000, False, True)` (`cells=2`).

## Gotchas

- `AY` looks up the Słownik through the external link and shows `#N/D` without the Słownik on this Mac; only `AU:AX` must be free of errors.
- A Wzorzec whose external link no formula uses proves nothing: Excel drops such a link on save. The doctor rejects that fixture; the old synthetic Wzorce of `verify-rozliczenia` have exactly that.
- A repair dialog surfaces here as `ExcelDialog … not open` with `Excel dialogs: [...]`; `features/okno-naprawy.md` shows what it looks like.
