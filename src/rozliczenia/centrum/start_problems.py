"""Katalog Komunikatów startu Centrum rozliczeń dla taty: co się stało, gdzie, co zrobić.

Bez konsoli (skrót ``pythonw``) Komunikat pokazuje natywne okienko, z konsolą
(``py -3 run_centrum.py``) trzy linie w konsoli. Treść nie zawiera tekstu wyjątku.
Instrukcja taty cytuje „Co się stało” każdego Komunikatu
(``tests/test_instrukcja_taty.py``). Moduł używa tylko biblioteki standardowej,
bo jeden z Komunikatów mówi o brakujących zależnościach.
"""

from __future__ import annotations

from rozliczenia.message import Message

TITLE = "Centrum rozliczeń"
_SHORTCUT = "skrót „Centrum rozliczeń”"
_LOG = "logs\\centrum-rozliczen.log"


def _address(port: int) -> str:
    return f"adres http://127.0.0.1:{port}/ na tym komputerze"


def port_taken(port: int) -> Message:
    """Port Centrum zajmuje program, który nie odpowiada jak Centrum rozliczeń."""

    return Message(
        code="PORT_ZAJETY",
        what=f"Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program.",
        where=_address(port),
        action=(
            f"Uruchom ponownie komputer i kliknij {_SHORTCUT}. Jeśli komunikat wraca, "
            "przekaż go osobie utrzymującej narzędzie."
        ),
    )


def other_version_running(port: int, version: str) -> Message:
    """Na porcie działa Centrum rozliczeń innej wersji, np. sprzed aktualizacji narzędzia."""

    return Message(
        code="INNA_WERSJA_CENTRUM",
        what=f"Działa już Centrum rozliczeń w innej wersji ({version}).",
        where=_address(port),
        action=f"W karcie Centrum kliknij „Zamknij Centrum rozliczeń”, potem kliknij {_SHORTCUT} ponownie.",
    )


def missing_library(name: str) -> Message:
    """Python na komputerze taty nie ma biblioteki z ``requirements.txt``."""

    return Message(
        code="BRAK_BIBLIOTEKI",
        what=f"Brakuje biblioteki potrzebnej Centrum rozliczeń ({name}).",
        where="Python na tym komputerze",
        action=(
            "W folderze narzędzia uruchom py -3 -m pip install -r requirements.txt, "
            f"potem kliknij {_SHORTCUT} ponownie."
        ),
    )


def unexpected_start_failure() -> Message:
    return Message(
        code="NIEOCZEKIWANY_BLAD_STARTU",
        what="Centrum rozliczeń nie wystartowało z nieoczekiwanego powodu.",
        where=f"dziennik Centrum {_LOG} w folderze narzędzia",
        action=(
            f"Kliknij {_SHORTCUT} ponownie. Jeśli komunikat wraca, przekaż dziennik osobie "
            "utrzymującej narzędzie."
        ),
    )


def not_started_after_update() -> Message:
    """Po Aktualizacji narzędzia nie wystartowała ani nowa wersja, ani stara, do której opiekun cofnął klon."""

    return Message(
        code="NIE_WYSTARTOWALO_PO_AKTUALIZACJI",
        what="Centrum rozliczeń nie wystartowało po aktualizacji narzędzia.",
        where="narzędzie na tym komputerze",
        action="Przekaż ten komunikat Maksowi.",
    )
