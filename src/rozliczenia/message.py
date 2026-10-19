"""Komunikat: bezpieczny tekst dla taty w trzech częściach i jedyny błąd zatrzymania, który go niesie.

Katalogi procesów (``preparation_messages``, ``settlement_messages``) i
katalog startu Centrum rozliczeń (``centrum.start_problems``) są tylko treścią:
każda ich fabryka zwraca ``Message``. Zatrzymanie Uruchomienia procesu to
``raise StopError(katalog.fabryka(...))``.

Trzy części nie zawierają pełnych ścieżek, treści wyjątków, adresów ani treści
wierszy; wskazują tylko nazwę pliku, folder, arkusz, kolumnę, wiersz albo
Wykonawcę. Kod jest unikalny w obrębie katalogu procesu
(``tests/test_instrukcja_taty.py``).

Moduł używa tylko biblioteki standardowej, bo Komunikat startu Centrum o
brakującej bibliotece musi działać bez zależności.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPORT_TO_MAINTAINER: Final = "Przekaż ten komunikat osobie utrzymującej narzędzie."


@dataclass(frozen=True)
class Message:
    """Komunikat: co się stało, gdzie, co zrobić; ta sama treść w terminalu i w Centrum rozliczeń.

    ``terminal_line`` to dawna jedna linia zatrzymania Przebiegu rozliczeń w
    terminalu (ADR 0004). Jest wyłącznie terminalowa: może zawierać pełną
    ścieżkę i nie trafia do Centrum rozliczeń.
    """

    code: str
    what: str
    where: str
    action: str
    terminal_line: str | None = None

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"

    @property
    def terminal_lines(self) -> list[str]:
        """Linie terminala: ``terminal_line``, jeśli jest, a w przeciwnym razie trzy części."""

        return [self.terminal_line] if self.terminal_line is not None else self.text.splitlines()


class StopError(Exception):
    """Zatrzymanie Uruchomienia procesu z Komunikatem z katalogu procesu.

    Treść dla taty jest w ``message``, nigdy w ``str(error)`` (ADR 0004):
    ``str(error)`` to sam kod Komunikatu, więc zapis wyjątku do logu nie
    przenosi pełnej ścieżki z ``terminal_line``.
    """

    def __init__(self, message: Message) -> None:
        super().__init__(message.code)
        self.message = message


def file_label(path: Path) -> str:
    """Plik z folderem, w którym leży, bez pełnej ścieżki, np. ``plik a.xlsx, folder config``."""

    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


def folder_label(directory: Path) -> str:
    """Folder z folderem nadrzędnym, bez pełnej ścieżki, np. ``folder INEA\\08_14_09_2026``."""

    return f"folder {directory.parent.name}\\{directory.name}" if directory.parent.name else f"folder {directory.name}"
