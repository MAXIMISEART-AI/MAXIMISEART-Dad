"""Jednorazowa, lokalna naprawa relacji externalLinks w już zapisanych plikach."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from pathlib import Path


def external_parts(path: Path) -> dict[str, tuple[zipfile.ZipInfo, bytes]]:
    with zipfile.ZipFile(path, "r") as archive:
        return {
            info.filename: (info, archive.read(info.filename))
            for info in archive.infolist()
            if info.filename.startswith("xl/externalLinks/")
        }


def replace_external_parts(path: Path, parts: dict[str, tuple[zipfile.ZipInfo, bytes]]) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.links.", suffix=".xlsx", dir=path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for info in source.infolist():
                if info.filename.startswith("xl/externalLinks/"):
                    continue
                target.writestr(info, source.read(info.filename))
            for info, data in parts.values():
                target.writestr(info, data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Przywraca relacje externalLinks z nietkniętego szablonu Excel."
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Wykonaj naprawę po utworzeniu kopii.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = args.directory.expanduser().resolve()
    reference = args.reference.expanduser().resolve()
    if not directory.is_dir():
        print(f"Brak folderu: {directory}")
        return 1
    if not reference.is_file():
        print(f"Brak pliku wzorcowego: {reference}")
        return 1

    parts = external_parts(reference)
    if not parts:
        print("Plik wzorcowy nie zawiera externalLinks.")
        return 1

    targets = sorted(
        path
        for path in directory.glob("*.xlsx")
        if path != reference and not path.name.startswith(("~$", "._")) and path.stem.strip()
    )
    print(f"Plik wzorcowy: {reference.name}")
    print(f"Pliki do sprawdzenia: {len(targets)}")
    if not args.apply:
        print("Tryb kontrolny: nic nie zmieniono. Dodaj --apply, aby wykonać naprawę.")
        return 0

    backup_directory = directory / "_backup_przed_naprawa_linkow"
    backup_directory.mkdir(exist_ok=True)
    changed = 0
    for target in targets:
        lock_path = target.with_name(f"~${target.name}")
        if lock_path.exists():
            print(f"Pominięto zablokowany plik: {target.name}")
            continue
        backup = backup_directory / target.name
        shutil.copy2(target, backup)
        replace_external_parts(target, parts)
        changed += 1
    print(f"Naprawiono: {changed}")
    print(f"Kopie zapasowe: {backup_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
