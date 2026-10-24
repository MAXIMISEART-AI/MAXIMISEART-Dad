"""Logi Uruchomienia (ADR 0015, #317) przez HTTP API Centrum: plik JSON na komputerze taty po każdym Uruchomieniu.

Testy czytają pliki z katalogu Logów obok dziennika Centrum, tak jak Maks dostanie je z komputera taty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, NoReturn

import pytest

from rozliczenia import settlement_messages
from rozliczenia.centrum import app, contract, runs
from rozliczenia.period_folder import PeriodFolderInaccessible

from tests.fixtures.centrum import TOOL_COMMIT, finished_view, views_until, without_times
from tests.fixtures.centrum_processes import (
    PreparingCentrum,
    SettlingCentrum,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.settlement import MARKED, SOURCE_NAME, write_quantity_source

AnyCentrum = PreparingCentrum | SettlingCentrum
KEYS = {
    "schema_version", "run_id", "process", "mode", "period", "started_at", "ended_at", "duration_ms", "tool",
    "result", "ending", "stop_kind", "issue_count", "messages", "technical_notes", "summary", "phases", "templates",
    "environment", "trace", "diagnosis",
}


def log_files(centrum: AnyCentrum) -> list[Path]:
    return sorted((centrum.log_path.parent / "uruchomienia").glob("*"))


def records(centrum: AnyCentrum) -> list[dict[str, Any]]:
    """Logi po kolei od startu; nazwy plików mają start z dokładnością do sekundy."""

    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in log_files(centrum)]
    return sorted(loaded, key=lambda record: datetime.fromisoformat(record["started_at"]))


def in_json(path: Path) -> str:
    """Ścieżka tak, jak stoi w tekście pliku JSON (w Windows z podwojonym ``\\``)."""

    return json.dumps(str(path))[1:-1]


def card_messages(view: dict[str, Any]) -> list[dict[str, str]]:
    return [*view["result"]["stops"], *view["result"]["warnings"]]


def three_parts(record: dict[str, Any]) -> list[dict[str, str]]:
    return [{part: message[part] for part in ("what", "where", "action")} for message in record["messages"]]


Ran = tuple[AnyCentrum, dict[str, Any]]


def _settlement(tmp_path: Path, *, dry_run: bool, include_unmapped: bool = False) -> Ran:
    centrum = settling_centrum(tmp_path, include_unmapped=include_unmapped)
    return centrum, run_to_end(centrum, dry_run=dry_run)


def _preparation(tmp_path: Path, *, dry_run: bool) -> Ran:
    centrum = preparing_centrum(tmp_path)
    return centrum, run_to_end(centrum, dry_run=dry_run)


def _existing_worker_settlements(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()
    return centrum, run_to_end(centrum, dry_run=False)


def _missing_collective_file(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.collective_file.unlink()
    return centrum, run_to_end(centrum, dry_run=True)


def _aborted_decision(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": "abort"})
    return centrum, finished_view(centrum.client)


def _broken_worker_config(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.configuration.worker_config.write_text(":: nie yaml", encoding="utf-8")
    return centrum, run_to_end(centrum, dry_run=False)


def _failing(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool, engine: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    def run(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)
        if engine:
            steered.engines.fail_engine = True
        else:
            steered.engines.fail_summary = True
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


def _adapter_net(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)
        run_outcome = contract.RunOutcome
        built: list[str] = []

        def broken_once(**fields: Any) -> contract.RunOutcome:
            built.append(fields["ending"])
            if len(built) == 1:
                raise ValueError("synthetic contract failure SYN-001")
            return run_outcome(**fields)

        monkeypatch.setattr(contract, "RunOutcome", broken_once)
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


def _core_failed(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    """Sam rdzeń Uruchomienia procesu rzuca wyjątkiem, więc nie oddaje wyniku: ostatnia siatka adaptera bez rdzenia."""

    def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)

        def broken(*args: object, **kwargs: object) -> NoReturn:
            raise ValueError("synthetic core failure SYN-002")

        monkeypatch.setattr(runs, "run_process", broken)
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


QUANTITY_WARNINGS = [("warning", "NIEZNANE_URZADZENIA"), ("warning", "KOLUMNY_Z_OPISU")]
UNEXPECTED = [("stop", "BLAD_NIEOCZEKIWANY")]


@dataclass(frozen=True)
class Ending:
    run: Callable[[Path, pytest.MonkeyPatch], Ran]
    mode: str
    result: tuple[str, str, str | None]
    """Wynik, sposób zakończenia i Rodzaj Zatrzymania."""
    messages: list[tuple[str, str]]
    """Rodzaj i kod każdego Komunikatu, w kolejności karty."""
    trace: str | None = None
    """Typ wyjątku w śladzie wywołań."""


ENDINGS = {
    "sukces-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True), "podgląd", ("OK", "finished", None), []
    ),
    "sukces-zapis": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=False), "zapis", ("OK", "finished", None), []
    ),
    "sprawdzenie-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True, include_unmapped=True),
        "podgląd",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        [("warning", "BRAK_MAPOWANIA")],
    ),
    "sprawdzenie-zapis": Ending(
        lambda tmp_path, _: _preparation(tmp_path, dry_run=False),
        "zapis",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        QUANTITY_WARNINGS,
    ),
    "dla-taty-zapis": Ending(
        _existing_worker_settlements, "zapis", ("BLAD_KRYTYCZNY", "stop", "for_tata"), [("stop", "FOLDER_ROZLICZEN_ISTNIEJE")]
    ),
    "dla-taty-podglad": Ending(
        _missing_collective_file,
        "podgląd",
        ("BLAD_KRYTYCZNY", "stop", "for_tata"),
        [("stop", "BRAK_PLIKU_ZBIORCZEGO")],
    ),
    "decyzja-przerwij": Ending(
        _aborted_decision, "zapis", ("BLAD_KRYTYCZNY", "stop", "for_tata"), [("stop", "PRZERWANO_NIEPELNY_OKRES")]
    ),
    "do-maksa-zapis": Ending(
        _broken_worker_config,
        "zapis",
        ("BLAD_KRYTYCZNY", "stop", "for_maks"),
        [("stop", "ZLA_KONFIGURACJA_WYKONAWCOW")],
    ),
    "wyjatek-zapis": Ending(
        _failing(settling_centrum, dry_run=False, engine=True),
        "zapis",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
    ),
    "wyjatek-podglad": Ending(
        _failing(preparing_centrum, dry_run=True, engine=True),
        "podgląd",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
    ),
    "po-silniku-podglad": Ending(
        _failing(settling_centrum, dry_run=True, engine=False),
        "podgląd",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PLANU")],
        "ValueError",
    ),
    "po-silniku-zapis": Ending(
        _failing(preparing_centrum, dry_run=False, engine=False),
        "zapis",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PODSUMOWANIA")],
        "ValueError",
    ),
    "po-silniku-adapter": Ending(
        _adapter_net(preparing_centrum, dry_run=True),
        "podgląd",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
    ),
    "bez-rdzenia-zapis": Ending(
        _core_failed(settling_centrum, dry_run=False),
        "zapis",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
    ),
}


@pytest.mark.parametrize("ending", ENDINGS.values(), ids=ENDINGS.keys())
def test_kazda_droga_zakonczenia_w_obu_trybach_daje_jeden_plik_logow_z_wynikiem_i_komunikatami_karty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: Ending
) -> None:
    centrum, view = ending.run(tmp_path, monkeypatch)

    [path] = log_files(centrum)
    [record] = records(centrum)
    card = view["result"]
    assert (record["run_id"], record["process"], record["period"]) == (view["run"]["id"], view["run"]["process"], PERIOD)
    assert record["mode"] == ending.mode
    assert (record["result"], record["ending"], record["stop_kind"]) == ending.result
    assert (card["result"], card["ending"], card["stop_kind"]) == ending.result
    assert [(message["kind"], message["code"]) for message in record["messages"]] == ending.messages
    assert three_parts(record) == card_messages(view)
    assert (record["trace"] or {}).get("exception_type") == ending.trace
    text = path.read_text(encoding="utf-8")
    assert "SYN-" not in text
    assert in_json(tmp_path) not in text and in_json(tmp_path.resolve()) not in text


def test_logi_maja_etapy_i_przetworzenia_szablonow_pracownika_z_wynikiem_wierszami_i_czasem(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    view = run_to_end(centrum, dry_run=False)

    [path] = log_files(centrum)
    [record] = records(centrum)
    assert record.keys() == KEYS
    assert (record["schema_version"], record["diagnosis"], record["trace"]) == (1, None, None)
    assert record["tool"] == {"wydanie": None, "commit": TOOL_COMMIT}
    assert record["phases"] == view["progress"]["phases"]
    assert [phase["state"] for phase in record["phases"]] == ["completed"] * 4
    assert [(template["wykonawca"], template["outcome"], template["rows"]) for template in record["templates"]] == [
        ("Adrian Testowy", "ZAPISANO", 2),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "PUSTY_SZABLON", 0),
    ]
    assert all(isinstance(template["duration_ms"], int) and template["duration_ms"] >= 0 for template in record["templates"])
    assert record["summary"] == view["result"]["summary"]
    assert (record["issue_count"], record["technical_notes"]) == (0, [])
    assert isinstance(record["duration_ms"], int)
    assert record["started_at"] <= record["ended_at"]
    assert re.fullmatch(rf"\d{{8}}T\d{{6}}Z-settlement-{view['run']['id']}\.json", path.name)


def test_logi_po_bledzie_samego_adaptera_maja_czas_liczbe_problemow_i_przetworzenia_szablonow_z_rdzenia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, view = _adapter_net(settling_centrum, dry_run=False)(tmp_path, monkeypatch)

    [record] = records(centrum)
    assert (record["ending"], view["result"]["ending"]) == ("after_engine", "after_engine")
    assert isinstance(record["duration_ms"], int)
    assert record["issue_count"] == 0
    assert [(template["wykonawca"], template["outcome"], template["rows"]) for template in record["templates"]] == [
        ("Adrian Testowy", "ZAPISANO", 2),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "PUSTY_SZABLON", 0),
    ]
    assert record["summary"] is None


def test_powtorka_zatrzymania_dla_taty_ma_w_logach_rodzaj_powtorka(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()

    first = run_to_end(centrum, dry_run=False)
    second = run_to_end(centrum, dry_run=False)

    by_run = {record["run_id"]: record["stop_kind"] for record in records(centrum)}
    assert by_run == {first["run"]["id"]: "for_tata", second["run"]["id"]: "repeated"}


def test_srodowisko_ma_system_python_i_pliki_procesu_z_rozmiarem_i_onedrive(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    onedrive = centrum.surroundings.onedrive
    assert onedrive is not None
    onedrive.online_only.add(centrum.collective_file)

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    environment = record["environment"]
    assert environment["system"] and environment["python"]
    assert environment["files"] == [
        {
            "name": "Wzorzec rozliczenia pracownika.xlsx",
            "size": centrum.configuration.worker_template.stat().st_size,
            "online_only": False,
        },
        {"name": f"Rozliczenie wew. {PERIOD}.xlsx", "size": None, "online_only": None},
        {"name": SOURCE_NAME, "size": centrum.collective_file.stat().st_size, "online_only": True},
    ]


def test_pliki_procesu_ktorych_nie_da_sie_wyliczyc_daja_logi_bez_plikow_bez_nieoczekiwanego_wyjatku_w_dzienniku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)

    def inaccessible(*_: object, **__: object) -> list[Path]:
        raise PeriodFolderInaccessible(centrum.period_directory)

    monkeypatch.setattr(app, "files_of_process", inaccessible)

    view = run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["environment"]["files"] is None
    assert (record["result"], view["result"]["result"]) == ("OK", "OK")
    assert "nieoczekiwany-wyjatek" not in centrum.log_path.read_text(encoding="utf-8")


def test_logi_nie_maja_tresci_komorek_wykonawcy_przy_wierszu_daty_dziennej_ani_pelnych_sciezek(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    unmapped = {**MARKED, "H": "ZNACZNIK-WYKONAWCA"}
    without_worker = {**MARKED, "H": None}
    write_quantity_source(centrum.collective_file, [MARKED, unmapped, without_worker])

    preview = run_to_end(centrum, dry_run=True)
    stopped = run_to_end(centrum, dry_run=False)
    write_quantity_source(centrum.collective_file, [MARKED])
    written = run_to_end(centrum, dry_run=False)

    assert [view["result"]["result"] for view in (preview, stopped, written)] == [
        "WYMAGA_SPRAWDZENIA",
        "BLAD_KRYTYCZNY",
        "OK",
    ]
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 3)
    sent = [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    assert len(texts) == 3
    texts += sent
    naming = [
        settlement_messages.unmapped_worker_warning(centrum.collective_file, "ZNACZNIK-WYKONAWCA").what,
        settlement_messages.unmapped_worker(centrum.collective_file, ["ZNACZNIK-WYKONAWCA"]).what,
    ]
    for what in naming:
        forms = (what, json.dumps(what)[1:-1])
        assert any(form in text for form in forms for text in texts), what
        texts = [text.replace(forms[0], "").replace(forms[1], "") for text in texts]
    forbidden = ("ZNACZNIK", "adrian.testowy", "2026-09-09", "09.09.2026", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []
    assert sum("Adrian Testowy" in text for text in texts) == 4, "Wykonawca z Konfiguracji w obu wynikach z planem"


def test_diagnoza_w_logach_nie_ma_tresci_komorek_ani_pelnych_sciezek(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    write_quantity_source(centrum.collective_file, [MARKED, {**MARKED, "H": "ZNACZNIK-WYKONAWCA"}])
    run_id = stopped_for_maks(centrum)
    centrum.collective_file.with_name(f"~${centrum.collective_file.name}").write_bytes(b"")

    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")

    assert response.status_code == 200, response.json()
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 2)
    [record] = records(centrum)
    assert "failed" in [check["state"] for check in record["diagnosis"]["checks"]], "Diagnoza z przyczyną w pliku Logów"
    sent = [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)] + sent
    forbidden = ("ZNACZNIK", "adrian.testowy", "2026-09-09", "09.09.2026", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []


def test_katalog_logow_bez_prawa_zapisu_daje_ten_sam_wynik_bez_komunikatu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    blocked = centrum.log_path.parent / "uruchomienia"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("", encoding="utf-8")

    view = run_to_end(centrum, dry_run=False)

    reference = settling_centrum(tmp_path / "bez-blokady")
    expected = run_to_end(reference, dry_run=False)
    assert without_times(view["result"]) == without_times(expected["result"])
    assert (view["result"]["stops"], view["result"]["warnings"], view["result"]["technical_notes"]) == ([], [], [])
    assert blocked.read_text(encoding="utf-8") == ""
    log = centrum.log_path.read_text(encoding="utf-8")
    assert 'nieoczekiwany-wyjatek typ=FileExistsError miejsce="po wyniku Uruchomienia procesu"' in log
    queue = (tmp_path / "config" / "zgloszenia" / "kolejka").glob("*")
    labels = sorted(re.sub(r"^\w+-\d{4}-(.+)-\w{8}\.json$", r"\1", path.name) for path in queue)
    assert labels == ["kontrola-ilosci", "logi-uruchomienia"], "Kontrola ilości i Logi w kolejce"
    [record] = centrum.metric_records()
    [expected_record] = reference.metric_records()
    assert without_times(record) == without_times(expected_record)


def test_logi_przezywaja_zamkniecie_i_ponowny_start_centrum(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    before = run_to_end(centrum, dry_run=True)
    [first] = log_files(centrum)
    first_bytes = first.read_bytes()

    centrum.restart()
    after = run_to_end(centrum, dry_run=True)

    assert [record["run_id"] for record in records(centrum)] == [before["run"]["id"], after["run"]["id"]]
    assert first.read_bytes() == first_bytes
