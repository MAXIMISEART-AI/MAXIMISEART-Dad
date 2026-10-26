"""Drive a running Centrum rozliczeń in Chromium the way Dad does and record the proof.

Each feature step pairs a user action with the resulting screen, the server's
answer, and the side effect on disk (settings file, picker dialogs, opened
paths). Screenshots and ARIA snapshots go to ``<evidence>/screenshots`` and
``<evidence>/aria``; API answers to ``<evidence>/api``; the run's state files
to ``<evidence>/state``.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from collections.abc import Callable
import functools
from pathlib import Path
import shutil
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright

from drive import (
    DEFAULT_REPEATS,
    EXPLICIT_FEATURES,
    aktualizacja,
    aktualnosc_i_onedrive,
    blad_odczytu,
    diagnoza,
    karta_z_logow,
    konfiguracja,
    kopie_intermax,
    kontrola_ilosci,
    logi_uruchomienia,
    metryki,
    pomiar_u_taty,
    powiadomienia,
    przebieg_rozliczen,
    przygotowanie_pliku_zbiorczego,
    start_i_zamykanie,
    tablica_okresow,
    uklad_folderow_taty,
    uporzadkowanie_intermax,
    ustawienia,
    uwaga_taty,
    uzupelnienie,
    wydajnosc,
    zgloszenie,
)
from drive.common import DAD_TIME_ZONE, DriveFailure, Run

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from skrypt_skilla import Parser

# aktualizacja moves the run's tool clone right after Konfiguracja shows it. Przygotowanie pliku zbiorczego
# appends to the metrics files that Metryki counts, so it runs after Metryki; blad-odczytu runs between them, before
# the week's first Uruchomienie; uzupelnienie shows what Dad fills in its Plik zbiorczy and restores the file, and
# Przebieg rozliczeń continues Dad's path from that Plik zbiorczy, and kontrola-ilosci sends its Kontrola ilości after two restarts of Centrum; Diagnoza stops Uruchomienia of an empty Folder okresu after Dad's week, and aktualnosc-i-onedrive diagnoses one more such stop with the
# scripted GitHub and OneDrive; zgloszenie sends one such stop to the file skrzynka Zgłoszeń, and
# uwaga-taty needs the skrzynka queue that kontrola-ilosci emptied; logi-uruchomienia matches every Uruchomienie
# of the week with its file of Logi; powiadomienia closes an Uwaga taty and that Zgłoszenie there; pomiar-u-taty
# clicks through the pages with the files
# of Dad's whole week; uporzadkowanie-intermax points the Rejestr zleceń to its INTERMAX files and back, so it runs after
# every feature that reads the Rejestr zleceń, and kopie-intermax after it, because uporzadkowanie-intermax counts the
# Kopie in their folder; start-i-zamykanie closes Centrum, so it stays last.
FEATURES = (
    "ustawienia",
    "tablica-okresow",
    "uklad-folderow-taty",
    "konfiguracja",
    "aktualizacja",
    "metryki",
    "blad-odczytu",
    "przygotowanie-pliku-zbiorczego",
    "uzupelnienie",
    "przebieg-rozliczen",
    "kontrola-ilosci",
    "diagnoza",
    "aktualnosc-i-onedrive",
    "zgloszenie",
    "uwaga-taty",
    "logi-uruchomienia",
    "karta-z-logow",
    "powiadomienia",
    "pomiar-u-taty",
    "uporzadkowanie-intermax",
    "kopie-intermax",
    "start-i-zamykanie",
)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_root("run root with fixture.json and a served Centrum")
    parser.add_argument("--url", required=True, help="Centrum URL from <root>/server.json.")
    parser.add_argument("--evidence", required=True, help="Evidence directory that survives cleanup.")
    parser.add_argument("--feature", choices=("all", *FEATURES, *EXPLICIT_FEATURES), default="all")
    parser.add_argument(
        "--baseline", type=Path, default=wydajnosc.BASELINE, help="wydajnosc: the baseline to compare with."
    )
    parser.add_argument(
        "--powtorzenia", type=int, default=DEFAULT_REPEATS, help="wydajnosc: repetitions per scenario and profile."
    )
    args = parser.parse_args(argv)
    run = Run(args.root, args.url, Path(args.evidence).resolve())
    drives: dict[str, Callable[[Run, Page], None]] = {
        "ustawienia": ustawienia.drive_settings,
        "tablica-okresow": tablica_okresow.drive_period_board,
        "uklad-folderow-taty": uklad_folderow_taty.drive_dad_layout,
        "konfiguracja": konfiguracja.drive_configuration,
        "aktualizacja": aktualizacja.drive_update,
        "metryki": metryki.drive_metrics,
        "blad-odczytu": blad_odczytu.drive_load_failures,
        "przygotowanie-pliku-zbiorczego": przygotowanie_pliku_zbiorczego.drive_preparation,
        "uzupelnienie": uzupelnienie.drive_filling,
        "przebieg-rozliczen": przebieg_rozliczen.drive_settlement,
        "kontrola-ilosci": kontrola_ilosci.drive_quantity_check,
        "diagnoza": diagnoza.drive_diagnosis,
        "aktualnosc-i-onedrive": aktualnosc_i_onedrive.drive_freshness_and_onedrive,
        "zgloszenie": zgloszenie.drive_report,
        "uwaga-taty": uwaga_taty.drive_dad_note,
        "logi-uruchomienia": logi_uruchomienia.drive_run_logs,
        "karta-z-logow": karta_z_logow.drive_run_card_from_logs,
        "powiadomienia": powiadomienia.drive_notifications,
        "pomiar-u-taty": pomiar_u_taty.drive_measurement,
        "uporzadkowanie-intermax": uporzadkowanie_intermax.drive_intermax_ordering,
        "kopie-intermax": kopie_intermax.drive_intermax_copies,
        "start-i-zamykanie": start_i_zamykanie.drive_start_and_close,
        "wydajnosc": functools.partial(
            wydajnosc.drive_performance, baseline_path=args.baseline.resolve(), repeats=args.powtorzenia
        ),
    }
    selected = FEATURES if args.feature == "all" else (args.feature,)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, locale="pl-PL", timezone_id=DAD_TIME_ZONE.key
                )
                page = context.new_page()
                page.set_default_timeout(10_000)
                for feature in selected:
                    drives[feature](run, page)
            except Exception:
                if "page" in locals():
                    page.screenshot(path=run.evidence / "screenshots" / "zz-failure.png", full_page=True)
                raise
            finally:
                browser.close()
    except (DriveFailure, AssertionError, PlaywrightError) as exc:
        print(f"DRIVE FAIL | {exc}", file=sys.stderr)
        return 1
    finally:
        for name in ("opened.jsonl", "dialogs.jsonl", "config/centrum-ustawienia.yaml", "logs/centrum-rozliczen.log"):
            source = run.root / name
            if source.exists():
                shutil.copy2(source, run.evidence / "state" / source.name)
        logs = run.root / "logs" / "uruchomienia"
        if logs.is_dir():
            shutil.copytree(logs, run.evidence / "state" / logs.name, dirs_exist_ok=True)
    print(f"DRIVE OK | features={','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
