"""Komunikaty startu Centrum rozliczeń dla taty: co się stało, gdzie, co zrobić.

Bez konsoli (skrót ``pythonw``) komunikat pokazuje natywne okienko, z konsolą
(launcher ``.cmd``) trzy linie w konsoli. Treść nie zawiera tekstu wyjątku.
Instrukcja taty cytuje „Co się stało” każdego komunikatu
(``tests/test_instrukcja_taty.py``). Moduł używa tylko biblioteki standardowej,
bo jeden z komunikatów mówi o brakujących zależnościach.
"""

from __future__ import annotations

from dataclasses import dataclass

TITLE = "Centrum rozliczeń"
_SHORTCUT = "skrót „Centrum rozliczeń”"
_FALLBACK = "Do tego czasu używaj launcherów Przygotuj plik zbiorczy.cmd i Utwórz rozliczenia.cmd."
_LOG = "logs\\centrum-rozliczen.log"


@dataclass(frozen=True)
class StartProblem:
    code: str
    what: str
    where: str
    action: str

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"


def _address(port: int) -> str:
    return f"adres http://127.0.0.1:{port}/ na tym komputerze"


def port_taken(port: int) -> StartProblem:
    """Port Centrum zajmuje program, który nie odpowiada jak Centrum rozliczeń."""

    return StartProblem(
        code="PORT_ZAJETY",
        what=f"Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program.",
        where=_address(port),
        action=(
            f"Uruchom ponownie komputer i kliknij {_SHORTCUT}. Jeśli komunikat wraca, "
            f"przekaż go osobie utrzymującej narzędzie. {_FALLBACK}"
        ),
    )


def other_version_running(port: int, version: str) -> StartProblem:
    """Na porcie działa Centrum rozliczeń innej wersji, np. sprzed aktualizacji narzędzia."""

    return StartProblem(
        code="INNA_WERSJA_CENTRUM",
        what=f"Działa już Centrum rozliczeń w innej wersji ({version}).",
        where=_address(port),
        action=f"W karcie Centrum kliknij „Zamknij Centrum rozliczeń”, potem kliknij {_SHORTCUT} ponownie.",
    )


def missing_library(name: str) -> StartProblem:
    """Python na komputerze taty nie ma biblioteki z ``requirements.txt``."""

    return StartProblem(
        code="BRAK_BIBLIOTEKI",
        what=f"Brakuje biblioteki potrzebnej Centrum rozliczeń ({name}).",
        where="Python na tym komputerze",
        action=(
            "W folderze narzędzia uruchom py -3 -m pip install -r requirements.txt, "
            f"potem kliknij {_SHORTCUT} ponownie. {_FALLBACK}"
        ),
    )


def unexpected_start_failure() -> StartProblem:
    return StartProblem(
        code="NIEOCZEKIWANY_BLAD_STARTU",
        what="Centrum rozliczeń nie wystartowało z nieoczekiwanego powodu.",
        where=f"dziennik Centrum {_LOG} w folderze narzędzia",
        action=(
            f"Kliknij {_SHORTCUT} ponownie. Jeśli komunikat wraca, przekaż dziennik osobie "
            f"utrzymującej narzędzie. {_FALLBACK}"
        ),
    )
