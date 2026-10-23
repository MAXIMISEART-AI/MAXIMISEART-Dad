"""Atomowa zamiana pliku tekstowego Centrum: Zgłoszenia, ich plik w kolejce i pliki kolejki Skrzynki Zgłoszeń."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path


def replace_atomically(path: Path, text: str) -> None:
    """Zapisuje ``text`` jako ``path`` przez plik tymczasowy w tym samym folderze.

    Nieudany zapis (``OSError``) nie zostawia pustego ani urwanego pliku i nie niszczy poprzedniej treści.
    """

    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise
