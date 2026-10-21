# Przygotowanie pliku zbiorczego

The second process, run before the settlement. From a Rejestr zleceń it creates
the Rozliczenie wewnętrzne and the Plik zbiorczy of one period inside the Folder
okresu, both together or neither. Dad starts it in Centrum rozliczeń; outside
Centrum it runs as `tools/uruchom_proces.py preparation`.

## Sub-features

- `preparation-plan` dry-run reports order counts, skipped empty rows, orders per day, and both file names in `summary` and its warnings in `warnings`, and records the period in its metrics; it creates neither file nor the Folder okresu.
- `preparation-internal` writes every period order (successful or not) in Rejestr order to the Rozliczenie wewnętrzne, with `zwrot`/`UWAGI` empty; the Rejestr columns AKCJE, ZWROT and UWAGI reach neither period file.
- `preparation-collective` writes every Zlecenie skuteczne to `A:K` from row 18 of the Plik zbiorczy, leaving rates, sums, `N:AP` zeros, formulas, and sheets from the Wzorzec.
- `preparation-formatting` carries fill, font colour, bold, italic, and number format (dates included) from the Rejestr; widths and frozen header from the Wzorzec; font face/size from the Wzorzec cell, else its row style, else its column style; autofilter covers header plus data rows.
- `preparation-hyperlinks` gives every written cell the Hiperłącze of its Rejestr cell (the order in the company app behind `NUMER ZL.`) in both period files; a written cell without one keeps no Wzorzec hyperlink, and the address never reaches the JSON result, metrics or evidence.
- `preparation-links` keeps every `xl/externalLinks/*` part of the Wzorzec pliku zbiorczego byte-identical.
- `preparation-safety` leaves the Rejestr and both Wzorce byte-identical and leaves no staging directory.
- `preparation-real-templates` (local only) runs the same Rejestr into copies of the real Wzorce from `config/`: data font equals the header font, Wzorzec cells outside the written rows are unchanged, Wzorce and external links are byte-identical.
- `preparation-metrics` appends to its own history with counters `period_orders`, `successful_orders`, `skipped_empty_rows`, `warnings`.

## How to get to it (user POV)

- Dad starts it in Centrum rozliczeń, which takes the Rejestr and the folder okresów from Ustawienia taty and proposes the period; `verify-centrum-rozliczen` drives that route. In Dad's layout the folder okresów is `Załączniki` and the Folder okresu is found in `Rozliczenia {rok}\{miesiąc}\INEA`; the synthetic fixture uses the flat layout.
- The machine script never reads Ustawienia taty and requires the Rejestr, the folder okresów, and the period: `py -3 tools\uruchom_proces.py preparation --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --config <mapping> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and the machine script

Preconditions:

- The orchestrator builds the synthetic Rejestr in the layout of Dad's new Rejestr (empty column A, AKCJE in B, headers `ADRES`, `NUMER ZL.`, `NUMER UMOWY`, ZWROT and UWAGI at the end; decoy `lista` sheet, hidden `ARCHIWUM` sheet with an older order, empty export rows, orders outside the period, a late Monday order, highlights, a Hiperłącze in `NUMER ZL.` of every order), both Wzorce (the Wzorzec pliku zbiorczego with an external link), and a three-worker mapping under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation`. It runs `create_preparation_fixture.py`, `preparation_doctor.py`, the dry-run, `assert_preparation.py --expect dry-run`, the real run, `assert_preparation.py --expect run`, cleanup, and the self-test. Success prints `VERIFY OK | variant=preparation`.
- **Read the counts.** The fixture yields 5 period orders, 4 Zlecenia skuteczne, 4 skipped empty rows (every fully empty row from the first to the last period order, including the one before the next-period order), orders on Tue, Wed, Sat, Sun, and Mon, and 0 warnings. Adrian's Sunday order sits after the next-period order, so his two Zlecenia skuteczne are split by Kamil's in the Plik zbiorczy. Both runs exit `0`, and both JSON results carry this `summary`, `Ostrzeżenia` 0, and no `warnings`.
- **Read the workbook proof.** `assert-run.txt` confirms both period files, routed values, formatting, the Rejestr Hiperłącze of every written `NUMER ZL.` cell (`hyperlinks_from_rejestr=NUMER ZL.`), autofilters, preserved Wzorzec content, byte-identical external links, unchanged inputs, and two metrics records (`DRY-RUN`, `RUN`).
- **Check the real Wzorce.** When `config/` holds both Wzorce, run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation-real-templates`; in a worktree the runner reads the main checkout's `config/`, and `--templates-dir` overrides that. Without both Wzorce it prints `VERIFY SKIP`, which is a skip. Counts and summary match `preparation`; the `ASSERT OK` line in `assert-run.txt` contains `templates=config`. A failure names the column and both fonts, never a cell value.
- **Drive stops, warnings, and the row-style font.** The variant fixture reaches none of these; prove them with `py -3 -m pytest tests/test_collective_preparation.py tests/test_collective_preparation_stops.py -q`. They cover every stop and warning, including:
  - Wzorzec checks (missing, open in Excel, damaged, wrong header, WYKONAWCA outside H17 in the Wzorzec pliku zbiorczego) in Sprawdzanie, before the Rejestr is read, also in `--dry-run`;
  - merged Wzorzec cells in the rows orders will fill, which stop the run in Planowanie;
  - the "too few zero rows" warning, which still writes both files;
  - the row-style font fallback (`test_cells_without_own_style_take_wzorzec_row_font_before_column_font`).

  `tests/test_instrukcja_taty.py` keeps Dad's "komunikat → co zrobić" table in step with the message catalog.

## Gotchas

- Without `--dry-run`, an incomplete period (last order before the Monday) asks a Decyzja taty after the Planowanie stage. The machine script refuses every Decyzja taty, so such a run stops with exit `1` and writes nothing; keep a Monday order in the fixture.
- The period token uses the Monday's month and year (`27_02_11_2026`, `29_04_01_2027`), as in Dad's folders; the Tuesday-month form is rejected.
- An existing Folder okresu is allowed; an existing period file stops the run (Nienadpisywanie).
- Without `--config`, `--internal-template`, or `--collective-template` the script takes the files Centrum uses from `config/`; the orchestrator passes the fixture's files, so no run reads `config/`.
- The JSON result carries no row content; the `PREP-SYN-` markers in the fixture, the Hiperłącze addresses included (`caseId=PREP-SYN-LINK`), exist so the assertions and the self-test can catch a leak.
- The synthetic Wzorce do not reproduce every style layer of the real ones. Before #66 the code skipped the row style of the real Wzorzec rozliczenia wewnętrznego and wrote Calibri 11 instead of 10; `--variant preparation` passed, only `preparation-real-templates` failed. Run it after any change to how template styles are applied.
