---
name: verify-kopia-wzorca
description: Check with generated Wiersze danych that every Rozliczenie pracownika written by the template copy (ADR 0008, `template_copy.py`) is the file the old openpyxl path would write, keeps the rest of the Wzorzec byte for byte, and has the shape Excel needs. Use when a change touches `src/rozliczenia/template_copy.py`, `src/rozliczenia/sheet_data.py`, `WorkerSettlementTemplate` or `TemplateSheet.write_data_rows` in `src/rozliczenia/workbook_files.py`, `tools/porownanie_rozliczen.py`, or when `tests/test_kopia_wzorca.py` fails.
---

# Verify kopia Wzorca

## The promise

Przebieg rozliczeń does not load and save each Rozliczenie pracownika with openpyxl. It copies the
bytes of the Wzorzec rozliczenia pracownika and splices the Wiersze danych into the sheet XML
([ADR 0008](../../../docs/adr/0008-zapis-rozliczenia-pracownika-przez-podmiane-wierszy-danych.md)).
The check holds that copy to four rules, for any Wiersze danych:

- **WIERNA_KOPIA**: the Rozliczenie pracownika from the copy matches the file the old openpyxl path
  writes (`file_from_template` + `write_data_rows`) in everything Dad sees in Excel, as judged by
  the benchmark's correctness gate `tools/porownanie_rozliczen.py`: values, formulas, resolved
  styles, merges, row and column dimensions, defined names, external links, recalculation flags.
  Harm: a worker's quantities or amounts are wrong or formatted differently, and nothing stops.
- **TA_SAMA_ODMOWA**: the copy refuses a value (the run stops) exactly when the openpyxl path
  refuses it, and a refusal leaves no file behind. Harm: a stop that the old path would not make,
  or a file written from a value openpyxl rejects.
- **NIETKNIETY_WZORZEC**: what ADR 0008 promises stays byte for byte does stay so: every zip part
  except the sheet, `xl/workbook.xml` (only `calcPr` changes) and `xl/styles.xml` (styles are only
  appended), every sheet row outside the written Wiersze danych, the row attributes and the cells
  right of AT (formulas AU:AY) in written rows, and the Wzorzec file on disk. Harm: lost shared
  formulas, `calcChain` or external links, which openpyxl's view would not show.
- **KSZTALT_EXCELA**: the file has the shape Excel expects, which openpyxl does not check when it
  reads a file: zip CRCs, rows and cells in ascending order with references matching the row,
  `dimension` covering the written rows, `xml:space="preserve"` on text with spaces at either edge,
  `cellXfs` count matching its styles, unique `numFmtId`. Harm: Excel offers to repair the file or
  silently trims text.

## Does the change touch it?

Coverage, confirmed at **sync commit `c81d155`** (main, 2026-10-21):

| Code | What the check covers |
| --- | --- |
| `src/rozliczenia/template_copy.py` (all of it) | the code under verification |
| `src/rozliczenia/sheet_data.py` (`sheet_data_bounds`, `sheet_rows`) | row index the copy splices on |
| `src/rozliczenia/workbook_files.py`: `WorkerSettlementTemplate` (`check`, `create_settlement`, `_read`, `_template_copy`, `_create_with_openpyxl`), `_write_atomically`, `_package_writer` | the real entry point; which path it takes |
| `src/rozliczenia/workbook_files.py`: `file_from_template`, `TemplateSheet.write_data_rows`, `_request_full_recalculation`, `save_workbook` | the reference (old openpyxl path) |
| `tools/porownanie_rozliczen.py` (`compare_worker_settlements` and its per-cell helpers) | the judge for WIERNA_KOPIA |
| `tools/syntetyczne_wzorce.py` (`write_settlement_template`), `tests/fixtures/settlement.py` (`write_template`), `tests/fixtures/workbooks.py` (`add_external_link_fixture`) | the Wzorce under test |

Run the check when a diff touches any of these. To see whether the covered code moved since the
sync commit:

```bash
git diff --stat c81d155 -- src/rozliczenia/template_copy.py src/rozliczenia/sheet_data.py src/rozliczenia/workbook_files.py tools/porownanie_rozliczen.py tools/syntetyczne_wzorce.py
```

Changes elsewhere (reading the Plik zbiorczy, `engine.py`, publication of the Folder rozliczeń
pracowników) do not matter here.

## Run

```powershell
py -3 .agents\skills\verify-kopia-wzorca\scripts\check_template_copy.py
```

On macOS or Linux use `.venv/bin/python` instead of `py -3`. It needs the repo's test
dependencies (`hypothesis` is in `requirements.txt` and the `test`/`dev` extras), takes about
30 s on a Mac M4 Max when it passes and runs in CI as `tests/test_kopia_wzorca.py`. A failing run
spends up to a minute more shrinking the counterexample (`SHRINK_SECONDS`). In a worktree,
create its own `.venv` first (`tools/setup_worktree.py`); the script refuses to run against another checkout's
`src`.

The last line is the verdict:

| Last line | Exit | Meaning |
| --- | --- | --- |
| `KOPIA WZORCA OK` | 0 | All four rules hold in every example. |
| `KOPIA WZORCA OK, ZNANE USTALENIA: n` | 0 | Only the known findings below, each printed with its example. |
| `KOPIA WZORCA: NOWE NARUSZENIE (n)` | 1 | A rule breaks in a way not listed below. The shrunk counterexample is printed. |
| `KOPIA WZORCA: LUKA SPRAWDZENIA (n)` | 2 | The run did not exercise what it must: the copy was used less often than the openpyxl fallback, a reachable compression chunk start was never crossed, `rozliczenia` was imported from another checkout, or the checker itself failed (`błąd samego sprawdzenia`). No verdict on the rules. |

Options:

- `--seed N --examples 300` draws fresh random examples instead of the fixed derandomized set.
  Use it after a larger change to `template_copy.py`; one seed takes a few minutes. Run seeds one
  after another, not in parallel.
- `--wzorzec "<path>\Wzorzec rozliczenia pracownika.xlsx"` checks Dad's real Wzorzec instead of the
  synthetic ones (read only, copied to a temp folder; it has no client data). On Maks's Mac it is in
  `~/MAXIMISEART-Dad/config/`. Each example loads 10 thousand rows three times and the
  process needs about 1 GB of memory, so use `--examples 15` (about 4 minutes) and run nothing else beside it.
- `--strict` counts known findings as violations. `--no-shrink` skips shrinking (used by the
  mutation check).

## How it works and what it covers

One Hypothesis example is one Przebieg rozliczeń: one `WorkerSettlementTemplate` is loaded and
checked once, then 1 to 3 Rozliczenia pracowników are made from it in a row, as `run_settlements()`
does for its workers. That catches state carried from one copy to the next, such as the
compressed chunks cached at the first copy. Each Wzorzec below gets its own Hypothesis run with the
full number of examples (60 by default), and three fixed examples first: the value-type rows of the
owner test in `tests/test_workbook_files.py`, one Rozliczenie pracownika with the most Wiersze danych
in scope (it crosses every reachable chunk start), and the known finding below. Each Rozliczenie
pracownika is written by the real `create_settlement()` and, separately, by the openpyxl path from the same Wzorzec, then judged.

| Wzorzec | Shape | Wiersze danych per Rozliczenie pracownika |
| --- | --- | --- |
| `syntetyczny` | Dad's Wzorzec in small, from `tools/syntetyczne_wzorce.py` with 200 Wiersze danych: Excel-written XML, shared formulas every 64 rows, `calcChain`, external link, `sharedStrings`, rows of zeros in N:V and X, date formats, no cells in A and B from row 139 (Dad: from row 609) | 0–260, so writes reach past the last formatted row and the trailing row 269; compression chunks start at rows 18, 82, 146, 210 |
| `maly` | openpyxl-written workbook with two formatted Wiersze danych, a second sheet, an external link, namespace prefixes in `workbook.xml` | 0–80 |
| `wzorzec-taty` (only with `--wzorzec`, then the only one) | Dad's real Wzorzec | 0–700, chunks from rows 18, 82, …, 658 |

Row counts are drawn both at random and from the counts whose last written row falls right
before, on, or right after each chunk start within reach and the end of the sheet. The run reports
`granice kawałków przekroczone: k/n` and is a LUKA SPRAWDZENIA unless every reachable chunk start
was crossed by a Rozliczenie pracownika written through the copy. Each row usually has 46
values (A:AT), as from Plik zbiorczy, and sometimes fewer or more. Values cover what reading a Plik
zbiorczy gives and what openpyxl accepts: `None`, text (XML specials, spaces at the edges, line
breaks, `_x000D_`, emoji, 32 767 characters and longer), formulas and `=`, error codes, integers past
2^53, floats (NaN, infinities, subnormals, −0), `Decimal`, booleans, dates, datetimes, times and
durations including dates before 1900-03-01. About one value in 60 is one that sends the file down
the old path or refuses it: control characters, time zones, signalling NaN, rich text, array
formulas, bytes. The default run is derandomized, so it gives the same examples every time.

Not covered:

- This is testing with generated inputs, not a proof. Python has no verifier that runs on code
  built from `zlib`, regexes and byte slicing; a bug that needs a value or a row count the
  generator does not reach can pass.
- The reference is the openpyxl path, and the judge reads both files with openpyxl. A defect
  shared by both paths, or a difference openpyxl hides when reading, is invisible, apart from
  what KSZTALT_EXCELA checks. Excel itself is never run.
- Only the Wzorce above. Wzorce of other shapes go the old way (`UnsupportedShape`), and that
  routing decision is not checked.
- Reading the Plik zbiorczy, the engine, the publication of the Folder rozliczeń pracowników, the
  Wzorzec changing on disk between Sprawdzanie and Zapisywanie, and file system failures.

## Known findings

1. **PUSTA_KOMORKA_BEZ_STYLU_KOLUMNY** (WIERNA_KOPIA). When a Wiersz danych has an empty value in
   a cell that the Wzorzec XML does not have, the copy writes `<c r="A609"/>` with no style. The
   openpyxl path writes nothing there, so Excel shows the column's style, and the copy shows the
   default style. In Dad's real Wzorzec, rows 18–608 have every cell A:AT and from row 609 A and B
   have none, so this reaches Dad only in a Rozliczenie pracownika with at least 592 Wiersze danych
   and an empty A or B. The fixed example is the first gap row of `syntetyczny` (row 139).

A known finding is a real divergence in the current code. It is printed on every run until the
code is fixed, and the checker then stops printing it: delete its entry from `KNOWN_FINDINGS` in
`check_template_copy.py` and from this list. Only a cell that matches the finding exactly (style
difference only, empty on both sides, absent from the Wzorzec, written by the copy as a bare
`<c r=".."/>`) is put down to it; any other difference in the same file still fails the check.

## When the check fails

Read the counterexample as a story: step 1 loads the Wzorzec, each next step is one Rozliczenie
pracownika with its row count, row range and non-empty values (`K82=datetime(...)`), and the
lines with `→` name the rule, the Rozliczenie pracownika and the cells or parts that differ. Then
sort it into one of three cases:

- **Real bug**: a Plik zbiorczy could carry those values (or a Wzorzec of that shape could exist),
  and the copy is the side that differs. Report it with the story in those words. Fix the product
  code only if the user asks. If the user accepts the divergence instead, record the decision
  (ADR 0008 or a new ADR), add a key and description to `KNOWN_FINDINGS`, teach `_cell_differences`
  to attribute exactly that pattern to it, and add it to Known findings here.
- **Modeling error**: the checker is wrong. For example a rule reads XML the copy is allowed to
  write differently (prefixed tags, attribute order the ADR allows), the reference was written
  differently from `run_settlements()`, or the generator made a value that can never reach a
  Wiersz danych and both paths treat differently for an irrelevant reason. Fix the checker, then
  rerun the mutations below.
- **LUKA SPRAWDZENIA**: the run lost coverage, usually because a new refusal or fallback became
  common (look at `Rozliczenia pracowników: kopia …, droga openpyxl …, odmowa …` and the refusal
  types) or the Wzorzec generator changed its row count. Make the rare values rarer or fix the
  Wzorzec setup in `build_templates`.

Never loosen a rule, widen the known-finding pattern, or drop a value or Wzorzec to make a real
counterexample disappear.

## After changing the checker or an intended change to the copy

Prove the check can still fail. This applies broken variants to a temporary copy of `src`, never
to the checkout:

```powershell
py -3 .agents\skills\verify-kopia-wzorca\scripts\check_copy_mutations.py
```

It must end with `MUTACJE OK`: each of the nine mutations (sheet CRC over the head only, chunks
without a full flush, a dropped chunk, `dimension` not extended, a date without a date format, an
empty value keeping the Wzorzec's zero, 15 significant digits, `xml:space` only for leading
spaces, `&` not escaped) must give `KOPIA WZORCA: NOWE NARUSZENIE`. It takes about 10 s. A
mutation reported as `NIEAKTUALNA` no longer matches `template_copy.py`: rewrite its `anchor` and
`replacement` in `check_copy_mutations.py` against the new code so that it breaks the same rule again.

When the copy changes on purpose, also confirm that the checker still describes it: the rules
still state what ADR 0008 promises, the Wzorce still have the shapes in the table above, and the
coverage table names the current functions. Then run the check, a few `--seed` runs and the
mutations. Only after that, move the sync commit in "Does the change touch it?" to the commit you
checked. If the copy moves to another file, update `VERIFIED_FILE` in `check_template_copy.py`,
`VERIFIED` in `check_copy_mutations.py`, the coverage table and this skill's description.
