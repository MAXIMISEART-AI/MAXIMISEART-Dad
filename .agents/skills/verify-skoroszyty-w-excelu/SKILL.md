---
name: verify-skoroszyty-w-excelu
description: Verify in real Microsoft Excel for Mac (AppleScript) that the files of MAXIMISEART-Dad's processes open without a dialog, keep their external link, formulas, Wyróżnienia and Wygląd Wiersza danych (row heights Excel auto-fits, DATA as in the Plik zbiorczy), and that a Gotowość typed and saved in Excel reaches the Rozliczenia pracowników; use after changes to how workbooks are written or read, external links, Wyróżnienia, the Wzorce, or Gotowość. Local only, because it needs this Mac's Excel.
pilnuje:
  - src/rozliczenia/workbook_files.py
  - src/rozliczenia/template_copy.py
  - src/rozliczenia/row_look.py
  - src/rozliczenia/sheet_data.py
  - src/rozliczenia/highlights.py
  - src/rozliczenia/hyperlinks.py
  - src/rozliczenia/input_rows.py
  - src/rozliczenia/dated_rows.py
  - src/rozliczenia/collective_file.py
  - src/rozliczenia/preparation_register.py
  - src/rozliczenia/preparation_files.py
  - src/rozliczenia/template_settlement.py
  - tools/syntetyczne_wzorce.py
  - requirements.txt
---

# Verify skoroszyty w Excelu

Dad never sees a workbook through openpyxl: he opens the Plik zbiorczy in
Excel, types quantities and charges, saves, and later opens each Rozliczenie
pracownika. `verify-rozliczenia` proves the processes on file contents and
simulates Gotowość with openpyxl; this skill proves the same path in the real
Excel. Its failures are Excel's view: a repair dialog, a dropped link, a formula
showing `#N/D`, a Gotowość that Przebieg rozliczeń does not carry over.

Excel for Mac stands in for Dad's Excel for Windows. What it cannot prove:
Windows-only dialogs (Protected View, Windows links prompts), Dad's locale
parsing typed text (`25,5`), and his real Słownik behind the external link.
The Hiperłącza of `NUMER ZL.` are checked in the bytes Excel saved and
Przebieg rozliczeń wrote, not as Excel shows them or opens them on a click.

## Launch

From the repository root, after `tools/setup_worktree.py` in a worktree:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/run_excel_verification.py
```

One command runs the whole path. It ends with `VERIFY OK | wzorce=prawdziwe |
steps=28 | … | scratch_removed=true | evidence_kept=true | evidence=<dir>`. On
Maks's Mac with Excel 16.114 it took 2:56 with Dad's Wzorce and 77 s with
`syntetyczne`.

- `--wzorce prawdziwe` (default) copies Dad's three Wzorce from `config/`, in a
  worktree from the main checkout's `config/` (`--templates-dir` overrides).
  Without all three it prints `VERIFY SKIP`: report it as a skip, never a proof.
- `--wzorce syntetyczne` builds Wzorce of Dad's shape with
  `tools/syntetyczne_wzorce.py`; use it when the real Wzorce are absent.
- `--kontrola-naprawy` adds `features/okno-naprawy.md`; it is the only step
  that needs a human click.

The Rejestr zleceń, Wykonawcy and orders are always the synthetic ones of
`verify-rozliczenia`'s `create_preparation_fixture.py`, so no customer data
enters a run.

Excel is a shared, single-instance app. Before it looks at Excel, the runner
locks `~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/excel.lock`,
one lock for the whole Mac, so a run from any worktree refuses to start with
`VERIFY FAIL | ExcelBusy: … (pid <n>, <worktree>)` while another drives Excel.
The kernel drops the lock when its process ends, so a killed run blocks no
one. The runner starts Excel itself when Excel is not running, and quits it at
the end only then and only when no workbook is left. Workbooks of the user stay
untouched: every call addresses a workbook by its full path on the desk.

### The desk

Every workbook Excel opens is a byte copy on the **desk**,
`~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/<run>/`,
inside Excel's sandbox container. This is what makes the run need no human:

- a file outside the container opened from AppleScript waits on Excel's
  sandbox panel `Otwórz`;
- a file opened through Finder (`open -a`) asks `Ten skoroszyt zawiera linki
  do innych zewnętrznych źródeł danych…` with `Nie aktualizuj` / `Aktualizuj`;
- a file on the desk opened with `open workbook … update links do not update
  links` asks nothing.

The Plik zbiorczy saved by Excel on the desk is copied back into the Folder
okresu, so Przebieg rozliczeń reads exactly the bytes Excel wrote.

## Doctor

The runner runs the doctor after creating the fixture; its output is
`doctor.txt` in the evidence. To check by hand:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel_doctor.py --root <run root> --desk <desk>
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py status
```

`DOCTOR OK` means: macOS, Excel installed, Excel's container exists, the desk is
empty, both linked Wzorce have an external link used by a formula, the fixture
has no Folder okresu yet, and a running Excel answers AppleScript with no dialog
and holds no workbook named like this run's (Excel refuses two workbooks of the
same name). `excel.py status` is the read-only check of Excel alone.

`excel.py` names an AppleScript failure by its number. `-1743` raises
`ExcelNotPermitted`: macOS denies the app running the agent control of Excel,
and the run says so at once, also while it starts Excel. In System Settings →
Prywatność i ochrona → Automatyzacja, switch Microsoft Excel on for that app.
`-1708` and `-1712` raise `ExcelDialog`. When AppleScript gets no answer at
all (`-1712` even for Finder), macOS lost the Automatyzacja consent prompt;
the same setting fixes it.

## Drive

`run_excel_verification.py` runs, in order:

1. `tools/syntetyczne_wzorce.py` (only `syntetyczne`), then
   `create_preparation_fixture.py --with-worker-template --templates-from …`
   into `<run root>/okres`.
2. The doctor.
3. Przygotowanie pliku zbiorczego through `tools/uruchom_proces.py
   preparation` (JSON result, exit `0`).
4. Both Wzorce opened in Excel as the reference: their link names and the R1C1
   formulas of `AU18:AY18`.
5. [Otwarcie plików okresu](features/otwarcie-plikow-okresu.md).
6. [Gotowość w Excelu](features/gotowosc-w-excelu.md).
7. Przebieg rozliczeń through `tools/uruchom_proces.py settlement` on the
   Plik zbiorczy Excel saved.
8. [Rozliczenia pracowników w Excelu](features/rozliczenia-pracownikow-w-excelu.md).
9. With `--kontrola-naprawy`, [Okno naprawy](features/okno-naprawy.md).

Each behaviour prints `STEP <feature> | <id> | OK`. The first failing check
ends the run with `VERIFY FAIL | <reason>`; the reason names the file, row and
column, never a value. `features/README.md` holds the feature map and its
conventions.

Drive Excel only through `scripts/excel.py`; it encodes the traps below.

- `tell wb to save` saves; `save wb` returns without error and saves nothing.
- AppleScript gives numbers in the system locale (`305,75`) and a formula
  error as an empty text: find errors with `special cells … value errors`
  (`excel.error_cells`), never by reading values.
- Every entry recalculates the whole workbook (some 50 000 formulas in Dad's
  Wzorce), so type one row per call (`excel.type_row`); typed cell by cell,
  the first row of the synthetic Wzorce ran past the 60 s call limit.
- While a dialog is up, Excel answers `missing value` or fails with `-1708`,
  and both raise `ExcelDialog`; `excel.dialogs()` lists its untitled windows
  without any permission.

## Evidence

`<run dir>/evidence/excel-<id>/` survives cleanup (`--run-dir`, default
`.verification` of the checkout):

- `drive.txt`: every `STEP` line.
- `excel.json`: Excel version, which Wzorce, whether Excel ran before, per
  workbook the seconds to open, link count, rows checked, Wyróżnienia checked,
  the SHA-256 of the Plik zbiorczy Excel saved, and on failure its reason.
- `przygotowanie.json`, `przebieg.json`: the process results of
  `tools/uruchom_proces.py`.
- `fixture.txt`, `doctor.txt` (and `wzorce.txt` for `syntetyczne`),
  `cleanup.txt`.

Evidence carries names, counts, addresses and timings; the runner fails when a
file of it holds a synthetic row marker. There are no screenshots: the agent
has no Screen Recording permission, and Excel's own view is read through
AppleScript instead.

## Cleanup

The runner's `finally` closes, without saving, every workbook on the desk,
removes the desk and the run root, writes
`cleanup.txt`, and releases the lock; evidence stays. If a dialog keeps Excel from closing and this run
started Excel, it stops that process by its id, then starts Excel once more and
quits it, so macOS does not reopen the run's windows at the next start. A dialog
in an Excel that was already running stays for its owner to answer
(`excel_dialog_left=true`).

After a runner killed before its `finally`:

```bash
.venv/bin/python .agents/skills/verify-skoroszyty-w-excelu/scripts/excel.py close-under --root ~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja
rm -rf ~/Library/Containers/com.microsoft.Excel/Data/maximiseart-weryfikacja/<run>
.venv/bin/python .agents/skills/verify-rozliczenia/scripts/cleanup.py --root <run dir>/runs/<run>
```

## Helpers

- `scripts/run_excel_verification.py`: the one-command runner (Launch).
- `scripts/excel_doctor.py --root <run root> --desk <desk>`: the read-only
  doctor.
- `scripts/excel.py status | close-under --root <dir>`: Excel's state, and
  closing stranded workbooks; as a module, every Excel call of the runner.
- `tests/test_weryfikacja_w_excelu.py`: the error naming and the Mac-wide
  lock, with a fake `osascript`; part of `pytest`, so no Excel is needed.
- `scripts/excel_windows.js`: Excel's on-screen windows, run as
  `osascript -l JavaScript scripts/excel_windows.js`; a window without a title
  is a dialog.

Keep the feature map in step with what the runner checks; use
`/pstack:maintain-verification-skill` for that loop.
