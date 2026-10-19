"""Zapisuje kontrakt Centrum rozliczeń (OpenAPI z modeli Pydantic) dla generatora schematów zod.

Uruchamiane przez ``npm run contract`` w ``frontend/``; wynik trafia do
``frontend/src/api/openapi.json`` i jest commitowany razem z wygenerowanymi typami.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rozliczenia.centrum.app import create_app  # noqa: E402
from rozliczenia.centrum.platform import FileTypes  # noqa: E402


class _NoPlatform:
    """Kontrakt powstaje bez komputera taty: żadna akcja systemowa nie jest wywoływana."""

    def open_path(self, path: Path) -> None:
        raise AssertionError("Eksport kontraktu nie otwiera plików.")

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        raise AssertionError("Eksport kontraktu nie otwiera okien wyboru.")

    def choose_folder(self, title: str) -> Path | None:
        raise AssertionError("Eksport kontraktu nie otwiera okien wyboru.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "frontend" / "src" / "api" / "openapi.json")
    args = parser.parse_args()
    app = create_app(settings_path=ROOT / "config" / "centrum-ustawienia.yaml", platform=_NoPlatform())
    document = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(document.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
