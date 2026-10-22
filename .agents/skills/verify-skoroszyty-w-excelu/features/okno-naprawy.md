# Okno naprawy

When a workbook is damaged, Excel does not open it but asks: „W skoroszycie
„…” istnieje zawartość, która powoduje problem. Czy chcesz, aby program podjął
próbę odzyskania zawartości tego skoroszytu?” with `Tak` and `Nie`. That is the
dialog Dad saw after an old version damaged the external link parts (README,
„Naprawa plików zapisanych starą wersją”). This feature proves that the run
stops on such a dialog instead of passing or hanging.

## Sub-features

- `wykryte`: a copy of Darek Fikcyjny's Rozliczenie pracownika with an invalid `xl/externalLinks/externalLink1.xml` makes `excel.open_file` raise `ExcelDialog`, and `excel.dialogs()` lists Excel's untitled dialog window.
- `okno-zamkniete`: after a human answers `Nie`, Excel shows no dialog any more.

## How to get to it (user POV)

- Excel, double click on a damaged `.xlsx`: the question appears before any sheet.

## Driving it with AppleScript

Preconditions: the main path passed; run with `--kontrola-naprawy`. A human must be at the Mac.

- **Break a copy.** Write `Zepsute łącze.xlsx` on the desk: Darek's file with `<zepsute>` inserted after `<sheetDataSet>` in the external link part.
- **Open it.** `excel.open_file(…, timeout=30)` raises `ExcelDialog`; `excel.dialogs()` is not empty. `STEP okno-naprawy | wykryte | dialogs=1 | <W>x<H>`.
- **Hand over.** The runner prints `ACTION | W Excelu kliknij „Nie” …` and waits up to 10 minutes until `excel.dialogs()` is empty: `STEP okno-naprawy | okno-zamkniete`.

## Gotchas

- Excel has no AppleScript option to refuse the repair, and answering the dialog needs Accessibility (System Events), which the agent lacks; hence the click and the opt-in flag.
- The dialog and its detection were observed by hand on 2026-10-21 with a file opened through Finder. `--kontrola-naprawy` through the desk has not run yet; its first run is its proof.
- `Tak` repairs and opens the copy under its own name, without a sign of the repair in the name; only the dialog tells a repaired workbook apart.
