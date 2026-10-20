"""Zgłoszenie do Maksa z Centrum rozliczeń przez HTTP API, z fałszywą skrzynką Zgłoszeń."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import pytest

from rozliczenia import preparation_register
from rozliczenia.centrum.report_box import Refused, SendOutcome, Unreachable

from tests.fixtures.centrum import TOOL_COMMIT, project_version
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, run_to_end, stopped_for_maks
from tests.fixtures.preparation import PERIOD

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"


def with_key(centrum: PreparingCentrum) -> Path:
    """Klucz do Zgłoszeń w lokalnym pliku obok Ustawień taty, jak go wpisuje Maks."""

    key_file = centrum.tmp_path / "config" / "zgloszenia-klucz.txt"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    return key_file


def diagnose(centrum: PreparingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    return diagnosis


def send(centrum: PreparingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_wyslane_zgloszenie_jest_dokladnie_podgladem_z_diagnozy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    state = send(centrum, run_id)

    assert state == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert centrum.surroundings.report_box.keys == [KEY]


def test_zgloszenie_ma_komunikat_uruchomienie_narzedzie_diagnoze_i_dziennik(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    report = diagnose(centrum, stopped["run"]["id"])["report"]

    assert report["title"] == "BRAK_WZORCA: Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."
    body = report["body"]
    stop = stopped["result"]["stops"][0]
    for line in (
        "- Kod: BRAK_WZORCA",
        f"- Co się stało: {stop['what']}",
        f"- Gdzie: {stop['where']}",
        f"- Co zrobić: {stop['action']}",
        "- Proces: Przygotowanie pliku zbiorczego",
        f"- Okres: {PERIOD}",
        "- Tryb: DRY-RUN",
        f"- Wersja: {project_version()}",
        f"- Commit: {TOOL_COMMIT}",
        "| Wzorzec rozliczenia wewnętrznego | przeszło | Wzorzec rozliczenia wewnętrznego.xlsx przechodzi Sprawdzanie. |",
        f"| Wzorzec pliku zbiorczego | nie przeszło | {stop['what']} |",
        "| Folder okresu | przeszło | Folderu 08_14_09_2026 jeszcze nie ma. |",
    ):
        assert line in body.splitlines()
    log_lines = centrum.log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines[-2] in body  # ostatnie wpisy dziennika do Diagnozy włącznie z końcem Uruchomienia


def test_zgloszenie_nie_ma_tresci_wierszy_wyjatku_pelnych_sciezek_ani_klucza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)

    def fail_unexpectedly(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    monkeypatch.setattr(preparation_register, "read_register", fail_unexpectedly)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    monkeypatch.undo()
    diagnose(centrum, run_id)
    send(centrum, run_id)

    [report] = centrum.surroundings.report_box.sent
    text = report.title + report.body
    for forbidden in ("SYN-", "nieprzewidziany błąd", KEY, str(tmp_path), tmp_path.as_posix(), "Traceback"):
        assert forbidden not in text
    assert KEY not in centrum.log_path.read_text(encoding="utf-8")


def unsent_files(centrum: PreparingCentrum) -> dict[str, str]:
    directory = centrum.tmp_path / "config" / "zgloszenia"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md"))}


def test_bez_klucza_zgloszenie_zostaje_w_pliku_a_ponowna_proba_z_kluczem_je_wysyla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    saved = send(centrum, run_id)

    name = f"Zgłoszenie BLAD_PLANU {PERIOD}.md"
    assert saved == {
        "state": "saved",
        "message": {
            "what": "Nie wysłano Zgłoszenia: na tym komputerze nie ma klucza do Zgłoszeń.",
            "where": f"plik {name}, folder zgloszenia",
            "action": "Prześlij ten plik Maksowi mailem. Gdy Maks wpisze klucz do Zgłoszeń, kliknij „Spróbuj ponownie”.",
        },
    }
    assert unsent_files(centrum) == {name: f"# {preview['title']}\n\n{preview['body']}"}
    assert centrum.surroundings.report_box.sent == []

    with_key(centrum)
    again = send(centrum, run_id)

    assert again == {"state": "sent"}
    assert [report.body for report in centrum.surroundings.report_box.sent] == [preview["body"]]
    assert unsent_files(centrum) == {}


@pytest.mark.parametrize(
    ("failure", "what"),
    [
        (Refused(), "Nie wysłano Zgłoszenia: klucz do Zgłoszeń wygasł albo jest nieważny."),
        (Unreachable(), "Nie wysłano Zgłoszenia: brak połączenia z GitHubem."),
    ],
    ids=["odmowa", "brak-polaczenia"],
)
def test_nieudana_wysylka_zapisuje_zgloszenie_w_pliku_a_ponowna_proba_je_wysyla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: SendOutcome, what: str
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    centrum.surroundings.report_box.outcomes.append(failure)
    run_id = stopped_for_maks(centrum, monkeypatch)
    preview = diagnose(centrum, run_id)["report"]

    saved = send(centrum, run_id)

    assert (saved["state"], saved["message"]["what"]) == ("saved", what)
    assert list(unsent_files(centrum).values()) == [f"# {preview['title']}\n\n{preview['body']}"]

    assert send(centrum, run_id) == {"state": "sent"}
    assert (len(centrum.surroundings.report_box.keys), len(centrum.surroundings.report_box.sent), unsent_files(centrum)) == (2, 1, {})


def current_report(centrum: PreparingCentrum) -> object:
    view = centrum.client.get("/api/runs/current").json()
    return view["result"]["report"]


def test_wyslanie_jest_raz_na_zatrzymanie_a_wynik_uruchomienia_pokazuje_potwierdzenie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    assert current_report(centrum) == {"state": "ready"}
    diagnose(centrum, run_id)

    first, second = send(centrum, run_id), send(centrum, run_id)

    assert first == second == {"state": "sent"}
    assert len(centrum.surroundings.report_box.keys) == 1
    assert current_report(centrum) == {"state": "sent"}


def test_potwierdzenie_wyslania_przetrwa_restart_centrum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)
    body = diagnose(centrum, run_id)["report"]["body"]
    send(centrum, run_id)

    centrum.restart()
    again = stopped_for_maks(centrum, monkeypatch)

    assert current_report(centrum) == {"state": "sent"}
    diagnose(centrum, again)
    assert send(centrum, again) == {"state": "sent"}
    assert len(centrum.surroundings.report_box.keys) == 1
    sent = json.loads((tmp_path / "config" / "zgloszenia-wyslane.json").read_text(encoding="utf-8"))
    [fingerprint] = [line.removeprefix("- Odcisk problemu: ") for line in body.splitlines() if "Odcisk problemu" in line]
    assert sent == [{"fingerprint": fingerprint, "number": 1, "commit": TOOL_COMMIT, "state": "open"}]


def test_zatrzymanie_dla_taty_nie_proponuje_zgloszenia(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    (centrum.fixture.register_path.parent / f"~${centrum.fixture.register_path.name}").touch()

    view = run_to_end(centrum, dry_run=True)

    assert (view["result"]["stop_kind"], view["result"]["report"]) == ("for_tata", None)
    assert centrum.client.post(f"/api/runs/{view['run']['id']}/report").status_code == 409


def test_wyslanie_bez_diagnozy_jest_odrzucone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum, monkeypatch)

    refused = centrum.client.post(f"/api/runs/{run_id}/report")

    assert (refused.status_code, refused.json()) == (
        409,
        {"message": "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”."},
    )
    assert centrum.surroundings.report_box.keys == []


def test_konfiguracja_pokazuje_stan_klucza_do_zgloszen_bez_jego_wartosci(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    missing = centrum.client.get("/api/configuration").json()
    with_key(centrum)

    ready = centrum.client.get("/api/configuration")

    assert (missing["reports"], ready.json()["reports"]) == ("missing_key", "ready")
    assert KEY not in ready.text
