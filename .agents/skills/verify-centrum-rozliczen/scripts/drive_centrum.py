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
    diagnoza,
    konfiguracja,
    logi_uruchomienia,
    metryki,
    pomiar_u_taty,
    przebieg_rozliczen,
    przygotowanie_pliku_zbiorczego,
    start_i_zamykanie,
    tablica_okresow,
    uklad_folderow_taty,
    ustawienia,
    powiadomienie_o_naprawie,
    wydajnosc,
    zgloszenie,
)
from drive.common import DAD_TIME_ZONE, DriveFailure, Run

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from skrypt_skilla import Parser

# aktualizacja moves the run's tool clone right after Konfiguracja shows it. Przygotowanie pliku zbiorczego
# appends to the metrics files that Metryki counts, so it runs after Metryki; Przebieg rozliczeń continues Dad's
# path from its Plik zbiorczy; Diagnoza stops Uruchomienia of an empty Folder okresu after Dad's week, and aktualnosc-i-onedrive diagnoses one more such stop with the
# scripted GitHub and OneDrive; zgloszenie sends one such stop to the file skrzynka Zgłoszeń, and
# powiadomienie-o-naprawie closes that Zgłoszenie there; logi-uruchomienia matches every Uruchomienie of the week
# with its file of Logi; pomiar-u-taty clicks through the pages with the files
# of Dad's whole week; start-i-zamykanie closes Centrum, so it stays last.
FEATURES = (
    "ustawienia",
    "tablica-okresow",
    "uklad-folderow-taty",
    "konfiguracja",
    "aktualizacja",
    "metryki",
    "przygotowanie-pliku-zbiorczego",
    "przebieg-rozliczen",
    "diagnoza",
    "aktualnosc-i-onedrive",
    "zgloszenie",
    "powiadomienie-o-naprawie",
    "logi-uruchomienia",
    "pomiar-u-taty",
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
        "przygotowanie-pliku-zbiorczego": przygotowanie_pliku_zbiorczego.drive_preparation,
        "przebieg-rozliczen": przebieg_rozliczen.drive_settlement,
        "diagnoza": diagnoza.drive_diagnosis,
        "aktualnosc-i-onedrive": aktualnosc_i_onedrive.drive_freshness_and_onedrive,
        "zgloszenie": zgloszenie.drive_report,
        "powiadomienie-o-naprawie": powiadomienie_o_naprawie.drive_repair_notice,
        "logi-uruchomienia": logi_uruchomienia.drive_run_logs,
        "pomiar-u-taty": pomiar_u_taty.drive_measurement,
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
