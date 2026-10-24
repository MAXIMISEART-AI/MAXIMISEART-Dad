# Okno naprawy

When a workbook is damaged, Excel does not open it but asks: „W skoroszycie
„…” istnieje zawartość, która powoduje problem. Czy chcesz, aby program podjął
próbę odzyskania zawartości tego skoroszytu?” with `Tak` and `Nie`. That is the
dialog Dad saw after an old version damaged the external link parts; the
processes now copy those parts byte for byte. This feature proves that the run
stops on such a dialog instead of passing or hanging.

## Sub-features

- `wykryte`: a copy of Darek Fikcyjny's Rozliczenie pracownika with an invalid `xl/externalLinks/externalLink1.xml` makes `excel.open_file` raise `ExcelDialog`, and `excel.dialogs()` lists Excel's untitled dialog window.
- `okno-zamkniete`: after a human answers `Nie`, Excel shows no dialog any more.

## How to get to it (user POV)

- Excel, double click on a damaged `.xlsx`: the question appears before any sheet.

## Driving it with AppleScript

Preconditions: the main path passed; run with `--kontrola-naprawy`. A human must be at the Mac.

- **Break a copy.** Write `Zepsute łącze.xlsx` on the desk: Darek's file with `<zepsute>` inserted after `<sheetDataSet>` in the external link part.
- **Open it.** `excel.open_file(…, timeout=30)` raises `ExcelDialog`; `excel.dialogs()` is not empty. `STEP okno-naprawy | wykryte | OK | dialogs=<n> | <W>x<H>`.
- **Hand over.** The runner prints `ACTION | W Excelu kliknij „Nie” …` and waits up to 10 minutes until `excel.dialogs()` is empty: `STEP okno-naprawy | okno-zamkniete | OK`. The run then ends `steps=34`.

## Gotchas

- Excel has no AppleScript option to refuse the repair, and answering the dialog needs Accessibility (System Events), which the agent lacks; hence the click and the opt-in flag.
- The dialog and its detection were observed by hand on 2026-10-21 with a file opened through Finder. `--kontrola-naprawy` through the desk has not run yet; its first run is its proof.
- `excel.dialogs()` lists only windows on screen. While Excel is hidden (Cmd+H) it lists none, also with a workbook open (2026-10-24), so keep Excel visible for this check. Telling a dialog from a workbook window by its missing title needs Screen Recording (`SKILL.md`, Drive).
- Left unanswered in an Excel that ran before the run, the dialog keeps the cleanup from closing the copy: the run ends `VERIFY FAIL` with `close_failed=ExcelDialog` and `desk_kept=<desk>`, and the next run's sweep closes it (`SKILL.md`, Cleanup). Proven without Excel only (`tests/test_sprzatanie_excela.py`); the first `--kontrola-naprawy` left unanswered with Maks at the Mac is its live proof.
- `Tak` repairs and opens the copy under its own name, without a sign of the repair in the name; only the dialog tells a repaired workbook apart.
