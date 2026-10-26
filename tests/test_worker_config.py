"""Konfiguracja wykonawców: każda reguła pliku daje powód i bezpieczny szczegół.

Moduł nie zna katalogów Komunikatów; to, co tata zobaczy w Przebiegu
rozliczeń, Przygotowaniu pliku zbiorczego i Centrum rozliczeń, sprawdzają
testy tych procesów.
"""

from __future__ import annotations

import errno
from pathlib import Path
import sys

import pytest
import yaml

from rozliczenia.worker_config import WorkerConfigError, load_worker_mapping, normalize_text


def write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "worker_mapping.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_konfiguracja_wykonawcow_laczy_znormalizowany_identyfikator_z_nazwa_w_kolejnosci_pliku(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path,
        "schema_version: 1\nworkers:\n  '  Łukasz  KOWALSKI ': '  Łukasz Kowalski  '\n  adrian.m: Adrian Testowy\n",
    )

    assert load_worker_mapping(config_path) == {"łukasz kowalski": "Łukasz Kowalski", "adrian.m": "Adrian Testowy"}
    assert list(load_worker_mapping(config_path).values()) == ["Łukasz Kowalski", "Adrian Testowy"]


def test_przyklad_konfiguracji_wykonawcow_w_repozytorium_jest_poprawna_konfiguracja() -> None:
    example = Path(__file__).resolve().parents[1] / "config" / "worker_mapping.example.yaml"

    assert list(load_worker_mapping(example).values()) == ["Adrian Testowy", "Darek Fikcyjny", "Kamil Syntetyczny"]


def test_identyfikator_wykonawcy_jest_porownywany_bez_wielkosci_liter_i_nadmiarowych_spacji() -> None:
    assert normalize_text("  ŻANETA  Wójcik\n") == normalize_text("żaneta wójcik") == "żaneta wójcik"
    assert normalize_text(None) == ""


@pytest.mark.parametrize(
    "missing",
    [Path("brak.yaml"), Path("worker_mapping.yaml"), Path("plik") / "worker_mapping.yaml"],
    ids=["brak-pliku", "folder-zamiast-pliku", "plik-zamiast-folderu"],
)
def test_brak_pliku_konfiguracji_wykonawcow(tmp_path: Path, missing: Path) -> None:
    (tmp_path / "worker_mapping.yaml").mkdir()
    (tmp_path / "plik").write_text("", encoding="utf-8")

    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(tmp_path / missing)

    assert (raised.value.reason, raised.value.detail) == ("missing", "Nie można odczytać pliku konfiguracji.")


INACCESSIBLE = ("inaccessible", "Nie można teraz odczytać pliku konfiguracji. Plik może być zajęty przez inny program.")


@pytest.mark.parametrize(
    "error",
    [PermissionError(errno.EACCES, "Plik jest używany przez inny proces"), OSError(errno.EIO, "Błąd wejścia/wyjścia")],
    ids=["zajety", "blad-odczytu"],
)
def test_plik_konfiguracji_wykonawcow_bez_dostepu_jest_niedostepny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    config_path = write_config(tmp_path, "schema_version: 1\nworkers:\n  a: Wykonawca Testowy\n")

    def blocked(path: Path, encoding: str) -> str:
        raise error

    monkeypatch.setattr(Path, "read_text", blocked)

    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(config_path)

    assert (raised.value.reason, raised.value.detail) == INACCESSIBLE


@pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows nie odbiera prawa odczytu")
def test_plik_konfiguracji_wykonawcow_w_folderze_bez_dostepu_jest_niedostepny(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, "schema_version: 1\nworkers:\n  a: Wykonawca Testowy\n")
    tmp_path.chmod(0)
    try:
        with pytest.raises(WorkerConfigError) as raised:
            load_worker_mapping(config_path)
    finally:
        tmp_path.chmod(0o755)

    assert (raised.value.reason, raised.value.detail) == INACCESSIBLE


@pytest.mark.parametrize("encoding", ["cp1250", "utf-16"], ids=["ansi-notatnik", "powershell-5"])
def test_konfiguracja_wykonawcow_zapisana_poza_utf8(tmp_path: Path, encoding: str) -> None:
    config_path = tmp_path / "worker_mapping.yaml"
    config_path.write_text("schema_version: 1\nworkers:\n  łukasz: Łukasz Testowy\n", encoding=encoding)

    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(config_path)

    assert (raised.value.reason, raised.value.detail) == ("not_utf8", "Plik nie jest zapisany w kodowaniu UTF-8.")


def test_konfiguracja_wykonawcow_ktora_nie_jest_yaml(tmp_path: Path) -> None:
    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(write_config(tmp_path, "workers: [niedomknięta lista\n"))

    assert (raised.value.reason, raised.value.detail) == ("not_yaml", "Plik nie jest poprawnym YAML.")


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("- lista\n", "Konfiguracja musi być mapą z sekcją workers."),
        ("schema_version: 2\nworkers:\n  a: A\n", "Nieobsługiwana wersja konfiguracji."),
        ("schema_version: '1'\nworkers:\n  a: A\n", "Nieobsługiwana wersja konfiguracji."),
        ("schema_version: true\nworkers:\n  a: A\n", "Nieobsługiwana wersja konfiguracji."),
        ("schema_version: 1\n", "Konfiguracja workers musi zawierać co najmniej jeden wpis."),
        ("schema_version: 1\nworkers: {}\n", "Konfiguracja workers musi zawierać co najmniej jeden wpis."),
        (
            "schema_version: 1\nworkers:\n  7: Siódmy\n",
            "Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika.",
        ),
        (
            "schema_version: 1\nworkers:\n  a: [A]\n",
            "Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika.",
        ),
        (
            "schema_version: 1\nworkers:\n  '  ': A\n",
            "Konfiguracja zawiera pusty identyfikator lub nazwę pracownika.",
        ),
        ("schema_version: 1\nworkers:\n  a: '  '\n", "Konfiguracja zawiera pusty identyfikator lub nazwę pracownika."),
        (
            "schema_version: 1\nworkers:\n  Adrian: A\n  ' adrian ': B\n",
            "Konfiguracja zawiera powtórzony identyfikator pracownika.",
        ),
        (
            f"schema_version: 1\nworkers:\n  a: {'X' * 223}\n",
            "Konfiguracja zawiera nazwę pracownika zbyt długą dla nazwy pliku.",
        ),
        (
            "schema_version: 1\nworkers:\n  a: Ten Sam\n  b: ten sam\n",
            "Dwóch identyfikatorów wskazuje ten sam plik pracownika: Ten Sam / ten sam",
        ),
    ],
    ids=[
        "nie-mapa",
        "inna-wersja",
        "wersja-tekstem",
        "wersja-logiczna",
        "brak-workers",
        "puste-workers",
        "identyfikator-liczba",
        "nazwa-lista",
        "pusty-identyfikator",
        "pusta-nazwa",
        "powtorzony-identyfikator",
        "nazwa-za-dluga-dla-pliku",
        "dwa-identyfikatory-na-jedna-nazwe",
    ],
)
def test_zlamana_regula_konfiguracji_wykonawcow_ma_szczegol(tmp_path: Path, content: str, detail: str) -> None:
    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(write_config(tmp_path, content))

    assert (raised.value.reason, raised.value.detail) == ("invalid", detail)


@pytest.mark.parametrize("name", ["../poza", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b", "a\tb", "Kowalski."])
def test_nazwa_wykonawcy_niedozwolona_w_nazwie_pliku_w_windows_lamie_konfiguracje(tmp_path: Path, name: str) -> None:
    content = yaml.safe_dump({"schema_version": 1, "workers": {"a": name}}, allow_unicode=True)

    with pytest.raises(WorkerConfigError) as raised:
        load_worker_mapping(write_config(tmp_path, content))

    assert (raised.value.reason, raised.value.detail) == (
        "invalid",
        "Konfiguracja zawiera nazwę pracownika nieprawidłową dla nazwy pliku.",
    )
