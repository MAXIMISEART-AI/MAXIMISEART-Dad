"""Uszkodzony plik taty, który czyta Centrum rozliczeń, nie kończy się ogólnym Komunikatem.

Macierz: plik × uszkodzenie × wejście Centrum. Świat taty (Rejestr zleceń, trzy Wzorce, Plik
zbiorczy, Konfiguracja wykonawców, Ustawienia, metryki, dziennik, Logi Uruchomienia i pliki
Zgłoszeń) powstaje raz, a każdy przypadek dostaje jego kopię z jednym uszkodzonym plikiem albo folderem.
Ogólny Komunikat to 500 „nieoczekiwany błąd”, Uruchomienie zakończone nieoczekiwanym wyjątkiem
albo sprawdzenie Diagnozy „nieoczekiwany błąd”. Odmowa 500 z własnym tekstem jest zamierzona.
Plik albo folder bez dostępu jest niedostępny: żaden Komunikat nie nazywa go uszkodzonym.
Wejścia to operacje kontraktu Centrum; operacja spoza macierzy ma w ``NOT_SWEPT`` powód.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from datetime import date, datetime
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import zipfile
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.report_box import GitHubReportBox, HttpRequest, HttpResponse
from rozliczenia.centrum.shutdown import Shutdown

from tests.fixtures.centrum import CENTRUM, FakeGitHub, FakeOneDrive, FakePlatform, MetricsPaths, finished_view
from tests.fixtures.centrum_processes import Engines
from tests.fixtures.preparation import PERIOD, write_collective_template, write_internal_template, write_register
from tests.fixtures.settlement import write_source, write_template

TODAY = date(2026, 9, 16)
SETTLEMENT_PERIOD = "01_07_09_2026"
# Słowo Komunikatu o zepsutym pliku; plik bez dostępu jest cały i tata nie ma go naprawiać w Excelu.
# Spacja odróżnia je od ścieżek tmp_path, które zawierają nazwę testu.
DAMAGED = " uszkodzon"
GENERIC_500 = "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie."
DIAGNOSIS_UNEXPECTED = "Nie udało się sprawdzić: nieoczekiwany błąd."

TEXT, LINES, XLSX, FOLDER = "tekst", "wiersze", "xlsx", "folder"
FILES: dict[str, tuple[str, str]] = {
    "ustawienia": ("config/centrum-ustawienia.yaml", TEXT),
    "konfiguracja_wykonawcow": ("config/worker_mapping.yaml", TEXT),
    "klucz_zgloszen": ("config/zgloszenia-klucz.txt", TEXT),
    "wyslane_zgloszenia": ("config/zgloszenia-wyslane.json", TEXT),
    "uwagi_taty": ("config/uwagi-taty.json", TEXT),
    "przeczytane_powiadomienia": ("config/powiadomienia.json", TEXT),
    "uruchomienia_centrum": ("config/centrum-uruchomienia.jsonl", LINES),
    "adresy_skrzynki": ("config/skrzynka-adresy.jsonl", LINES),
    "dziennik_centrum": ("logs/centrum-rozliczen.log", LINES),
    "logi_uruchomien": ("logs/uruchomienia", FOLDER),
    "metryki_przygotowania": (".przygotowanie-pliku-zbiorczego-metrics.jsonl", LINES),
    "metryki_przebiegu": (".rozliczenia-metrics.jsonl", LINES),
    "rejestr": ("ZLECENIA INTERMAX OD 08_11_2021.xlsx", XLSX),
    "wzorzec_wewnetrzny": ("config/Wzorzec rozliczenia wewnętrznego.xlsx", XLSX),
    "wzorzec_zbiorczy": ("config/Wzorzec pliku zbiorczego.xlsx", XLSX),
    "wzorzec_pracownika": ("config/Wzorzec rozliczenia pracownika.xlsx", XLSX),
    "plik_zbiorczy": (f"Załączniki/{SETTLEMENT_PERIOD}/Rozliczenie {SETTLEMENT_PERIOD} - zbiorcze.xlsx", XLSX),
    "folder_okresow": ("Załączniki", FOLDER),
    "folder_okresu": (f"Załączniki/{SETTLEMENT_PERIOD}", FOLDER),
    "folder_okresu_przygotowania": (f"Załączniki/{PERIOD}", FOLDER),
    "folder_zgloszen": ("config/zgloszenia", FOLDER),
}


def _empty(path: Path) -> None:
    path.write_bytes(b"")


def _bom(path: Path) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())


def _ansi(path: Path) -> None:
    path.write_bytes(path.read_text(encoding="utf-8").encode("cp1250"))


def _truncated(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])


def _torn_last_line(path: Path) -> None:
    data = path.read_bytes().rstrip(b"\n")
    start = data.rfind(b"\n") + 1
    multibyte = next((index for index, byte in enumerate(data[start:]) if byte >= 0xC0), None)
    path.write_bytes(data[: start + (multibyte + 1 if multibyte is not None else max(1, (len(data) - start) // 2))])


def _random_bytes(path: Path) -> None:
    path.write_bytes(random.Random(path.name).randbytes(4096))


def _rewrite_zip(path: Path, change: Callable[[str, bytes], bytes | None]) -> None:
    with zipfile.ZipFile(path) as source:
        entries = [(entry.filename, source.read(entry)) for entry in source.infolist()]
    with zipfile.ZipFile(path, "w") as damaged:
        for name, data in entries:
            changed = change(name, data)
            if changed is not None:
                damaged.writestr(name, changed)


def _truncated_sheet_xml(path: Path) -> None:
    _rewrite_zip(path, lambda name, data: data[: len(data) // 2] if name.startswith("xl/worksheets/") else data)


def _without_sheets(path: Path) -> None:
    _rewrite_zip(path, lambda name, data: None if name.startswith("xl/worksheets/") else data)


def _folder_instead_of_file(path: Path) -> None:
    path.unlink()
    path.mkdir()


def _file_instead_of_folder(path: Path) -> None:
    shutil.rmtree(path)
    path.write_bytes(b"")


def _inaccessible(path: Path) -> None:
    if sys.platform == "win32":  # chmod w Windows zmienia tylko atrybut „tylko do odczytu”
        subprocess.run(["icacls", str(path), "/deny", f"{os.environ['USERNAME']}:(RD)"], check=True, capture_output=True)
    else:
        path.chmod(0)
    with pytest.raises(PermissionError):
        list(path.iterdir()) if path.is_dir() else path.open("rb").close()


def _readable_again(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/remove:d", os.environ["USERNAME"]], check=True, capture_output=True)
    else:
        path.chmod(0o755)


DAMAGES: dict[str, tuple[tuple[str, ...], Callable[[Path], None]]] = {
    "pusty": ((TEXT, LINES, XLSX), _empty),
    "bom": ((TEXT, LINES), _bom),
    "ansi": ((TEXT, LINES), _ansi),
    "uciety": ((TEXT, LINES, XLSX), _truncated),
    "urwana_linia": ((LINES,), _torn_last_line),
    "losowe_bajty": ((TEXT, LINES, XLSX), _random_bytes),
    "xlsx_uciety_xml": ((XLSX,), _truncated_sheet_xml),
    "zip_bez_arkusza": ((XLSX,), _without_sheets),
    "katalog_zamiast_pliku": ((TEXT, LINES, XLSX), _folder_instead_of_file),
    "plik_zamiast_folderu": ((FOLDER,), _file_instead_of_folder),
    "bez_odczytu": ((TEXT, LINES, XLSX, FOLDER), _inaccessible),
}


@dataclass
class World:
    root: Path

    def path(self, name: str) -> Path:
        return self.root / FILES[name][0]

    @cached_property
    def engines(self) -> Engines:
        return Engines(MetricsPaths(self.path("metryki_przygotowania"), self.path("metryki_przebiegu")))

    def app(self) -> FastAPI:
        log = CentrumLog(self.path("dziennik_centrum"))
        # Drugie wskazanie dostaje wejście chooseRegister albo choosePeriodsDirectory po _remembering_choices.
        platform = FakePlatform(
            chosen_files=[self.path("rejestr")] * 2, chosen_folders=[self.path("folder_okresow")] * 2
        )
        return create_app(
            settings_path=self.path("ustawienia"),
            platform=platform,
            log=log,
            shutdown=Shutdown(log),
            today=lambda: TODAY,
            configuration_files=ConfigurationFiles(
                worker_config=self.path("konfiguracja_wykonawcow"),
                internal_template=self.path("wzorzec_wewnetrzny"),
                collective_template=self.path("wzorzec_zbiorczy"),
                worker_template=self.path("wzorzec_pracownika"),
            ),
            processes=self.engines.processes(),
            tool_freshness=FakeGitHub().freshness(),
            cloud_files=FakeOneDrive().cloud_files(),
            report_box=GitHubReportBox(transport=_offline_like_urllib),
        )

    def client(self) -> TestClient:
        return TestClient(self.app(), base_url=CENTRUM, headers={"Origin": CENTRUM})


def _remembering_choices(world: World) -> TestClient:
    """Centrum, w którym tata wskazał Rejestr zleceń i folder okresów tej kopii świata."""

    client = world.client()
    assert client.post("/api/settings/register/choose").status_code == 200
    assert client.post("/api/settings/periods-directory/choose").status_code == 200
    return client


def _offline_like_urllib(request: HttpRequest) -> HttpResponse:
    for name, value in request.headers.items():
        f"{name}: {value}".encode("latin-1")  # http.client.putheader koduje nagłówki w latin-1
    raise OSError("brak sieci u taty")


def _build(root: Path) -> None:
    world = World(root)
    world.path("folder_okresu").mkdir(parents=True)
    world.path("folder_okresu_przygotowania").mkdir()
    world.path("folder_zgloszen").mkdir(parents=True)
    write_register(world.path("rejestr"))
    write_internal_template(world.path("wzorzec_wewnetrzny"))
    write_collective_template(world.path("wzorzec_zbiorczy"))
    write_template(world.path("wzorzec_pracownika"))
    write_source(world.path("plik_zbiorczy"), include_unmapped=False)
    world.path("konfiguracja_wykonawcow").write_text(
        "# Wykonawcy zespołu z Łodzi\nschema_version: 1\nworkers:\n"
        "  adrian.testowy: Adrian Testowy\n  dariusz.fikcyjny2: Darek Fikcyjny\n  kamil.syntetyczny: Kamil Syntetyczny\n",
        encoding="utf-8",
    )
    world.path("klucz_zgloszen").write_text("github_pat_SYNTETYCZNY123\n", encoding="utf-8")
    world.path("wyslane_zgloszenia").write_text(
        json.dumps([SENT_REPORT], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    world.path("przeczytane_powiadomienia").write_text(
        json.dumps({"schema_version": 1, "przeczytane": [READ_NOTIFICATION]}) + "\n", encoding="utf-8"
    )
    client = _remembering_choices(world)
    assert client.post("/api/dad-notes", json=DAD_NOTE).json() == {"state": "waiting"}
    for process, period in (("preparation", PERIOD), ("settlement", SETTLEMENT_PERIOD)):
        started = client.post("/api/runs", json={"process": process, "period": period, "dry_run": True})
        assert started.status_code == 200, started.json()
        assert finished_view(client)["result"]["ending"] == "finished"
    remembered = world.path("uruchomienia_centrum").read_text(encoding="utf-8").splitlines()
    world.path("adresy_skrzynki").write_text(
        "".join(
            json.dumps({"run_id": json.loads(line)["run_id"], "label": "logi-uruchomienia", "url": url}) + "\n"
            for line, url in zip(remembered, LOGS_COMMENTS, strict=True)
        ),
        encoding="utf-8",
    )
    for name in ("metryki_przygotowania", "metryki_przebiegu", "uruchomienia_centrum", "dziennik_centrum", "uwagi_taty"):
        assert world.path(name).stat().st_size > 0, name
    assert len(list(world.path("logi_uruchomien").iterdir())) == 2, "Logi Uruchomienia obu podglądów"


Problems = list[str]
Seen = list[tuple[str, str]]  # (wejście, tekst odpowiedzi): to, co tata zobaczyłby w Centrum


def _http(response: Any, where: str, seen: Seen) -> Problems:
    seen.append((where, response.text))
    if response.status_code < 500:
        return []
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("message") == GENERIC_500:
        return [f"{where}: ogólne 500"]
    return []


@dataclass(frozen=True)
class Entry:
    operations: tuple[str, ...]  # operationId kontraktu Centrum, które wejście wywołuje
    call: Callable[[TestClient, Seen], Problems]


def _route(operation: str, method: str, path: str, body: object = None) -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        return _http(client.request(method, path, json=body), operation, seen)

    return Entry((operation,), call)


def _process_run(process: str, period: str, *, saving: bool = False) -> Entry:
    """Uruchomienie procesu do wyniku: Podgląd bez zapisu albo Uruchomienie z zapisem.

    Po Uruchomieniu z zapisem Przebieg rozliczeń zapisuje też Kontrolę ilości w kolejce.
    """

    where = "Uruchomienie z zapisem" if saving else "Podgląd bez zapisu"

    def call(client: TestClient, seen: Seen) -> Problems:
        started = client.post("/api/runs", json={"process": process, "period": period, "dry_run": not saving})
        problems = _http(started, "startRun", seen)
        if started.status_code != 200:
            return problems
        result = finished_view(client)["result"]
        seen.append((where, json.dumps(result, ensure_ascii=False)))
        if result["ending"] in ("unexpected", "after_engine"):
            problems.append(f"{where}: ogólny Komunikat ({result['ending']})")
        return problems + _http(client.get("/api/runs/current"), "getCurrentRun", seen)

    return Entry(("startRun", "streamRunEvents", "getCurrentRun"), call)


def _diagnosis(process: str, period: str, *, report: bool) -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        run_id = _run_with_diagnosis(client, process, period)
        if run_id is None:
            return []
        diagnosis = client.post(f"/api/runs/{run_id}/diagnosis")
        problems = _http(diagnosis, "diagnoseRun", seen)
        if DIAGNOSIS_UNEXPECTED in diagnosis.text:
            problems.append("Diagnoza: sprawdzenie zakończone nieoczekiwanym błędem")
        if report and diagnosis.status_code == 200:
            problems += _http(client.post(f"/api/runs/{run_id}/report"), "reportRun", seen)
        return problems

    return Entry(("startRun", "streamRunEvents", "diagnoseRun") + (("reportRun",) if report else ()), call)


def _pinned_dad_note() -> Entry:
    def call(client: TestClient, seen: Seen) -> Problems:
        runs = client.get("/api/dad-notes/runs")
        problems = _http(runs, "getDadNoteRuns", seen)
        if runs.status_code != 200 or not runs.json():
            return problems
        pinned = {**DAD_NOTE, "run_id": runs.json()[0]["run_id"]}
        return problems + _http(client.post("/api/dad-notes/draft", json=pinned), "draftDadNote", seen)

    return Entry(("getDadNoteRuns", "draftDadNote"), call)


def _run_with_diagnosis(client: TestClient, process: str, period: str) -> str | None:
    for _ in range(2):  # drugi raz to Powtórka, gdy pierwsze Zatrzymanie jest „dla taty”
        started = client.post("/api/runs", json={"process": process, "period": period, "dry_run": True})
        if started.status_code != 200:
            return None
        view = finished_view(client)
        if view["result"]["diagnosis"] is not None:
            return str(view["run"]["id"])
    return None


DAD_NOTE = {"title": "Plik zbiorczy otwiera się długo", "body": "Excel myśli przy nim minutę."}
SENT_REPORT = {
    "fingerprint": "syntetyczny-ślad",
    "number": 7,
    "commit": None,
    "what": "Nie znaleziono Wzorca pliku zbiorczego.",
    "sent_at": "2026-09-15T08:00:00+00:00",
    "closure": {"reason": "completed", "at": "2026-09-16T08:00:00+00:00"},
}
READ_NOTIFICATION = "zgloszenie-7-rozwiazana"
LOGS_COMMENTS = [
    "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/3#issuecomment-1",
    "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/4#issuecomment-2",
]
VIEW_TIMING = {"kind": "navigation", "page": "okresy", "ready_ms": 120, "fcp_ms": None, "skeleton_ms": 40, "requests": []}
ENTRIES: dict[str, Entry] = {
    "getSettings": _route("getSettings", "GET", "/api/settings"),
    "chooseRegister": _route("chooseRegister", "POST", "/api/settings/register/choose"),
    "choosePeriodsDirectory": _route("choosePeriodsDirectory", "POST", "/api/settings/periods-directory/choose"),
    "openRegister": _route("openRegister", "POST", "/api/settings/register/open"),
    "changeTheme": _route("changeTheme", "PUT", "/api/settings/theme", {"theme": "light"}),
    "getPeriodBoard": _route("getPeriodBoard", "GET", "/api/periods"),
    "openPeriodPath": _route(
        "openPeriodPath", "POST", f"/api/periods/{SETTLEMENT_PERIOD}/open", {"target": "collective_file"}
    ),
    "getQuantitiesToFill": _route("getQuantitiesToFill", "GET", f"/api/periods/{SETTLEMENT_PERIOD}/quantities-to-fill"),
    # Rozliczenia pracownika w świecie nie ma, bo zatrzymałoby Przebieg rozliczeń; operacja go nie czyta, a ścieżkę
    # wylicza z tych samych Ustawień, Folderu okresów i Folderu okresu, które macierz psuje.
    "openWorkerSettlement": _route(
        "openWorkerSettlement",
        "POST",
        f"/api/periods/{SETTLEMENT_PERIOD}/worker-settlements/open",
        {"worker": "Adrian Testowy"},
    ),
    "getRunSetup": _route("getRunSetup", "GET", "/api/runs/setup"),
    "getMetrics": _route("getMetrics", "GET", "/api/metrics"),
    "getConfiguration": _route("getConfiguration", "GET", "/api/configuration"),
    "getNotifications": _route("getNotifications", "GET", "/api/notifications"),
    "markNotificationsRead": _route(
        "markNotificationsRead", "POST", "/api/notifications/read", {"ids": [READ_NOTIFICATION]}
    ),
    "getToolUpdate": _route("getToolUpdate", "GET", "/api/tool-update"),
    "recordViewTiming": _route("recordViewTiming", "POST", "/api/view-timings", VIEW_TIMING),
    "draftDadNote": _route("draftDadNote", "POST", "/api/dad-notes/draft", DAD_NOTE),
    "sendDadNote": _route("sendDadNote", "POST", "/api/dad-notes", DAD_NOTE),
    "uwaga-przypieta": _pinned_dad_note(),
    "podglad[przygotowanie]": _process_run("preparation", PERIOD),
    "podglad[przebieg]": _process_run("settlement", SETTLEMENT_PERIOD),
    "zapis[przebieg]": _process_run("settlement", SETTLEMENT_PERIOD, saving=True),
    "diagnoza[przygotowanie]": _diagnosis("preparation", PERIOD, report=True),
    "diagnoza[przebieg]": _diagnosis("settlement", SETTLEMENT_PERIOD, report=False),
}
DIAGNOSIS_ENTRIES = ("diagnoza[przygotowanie]", "diagnoza[przebieg]")
# Operacja kontraktu poza macierzą i powód; nowa operacja trafia do ENTRIES albo tutaj.
NOT_SWEPT: dict[str, str] = {
    "getHealth": "tożsamość Centrum, nie czyta plików taty",
    "decideRun": "Decyzja taty tylko wznawia Uruchomienie, którego odczyty sprawdzają podglądy",
    "startToolUpdate": "aktualizacja zmienia katalog narzędzia, nie pliki taty (test_centrum_aktualizacja)",
    "reportToolUpdate": "wymaga nieudanej aktualizacji; klucz i wysłane Zgłoszenia sprawdza reportRun",
    "closeCentrum": "kończy Centrum testu",
}


# Znane przypadki: powód, termin i zgoda Maksa. Po terminie przypadek znów pada, a naprawiony pada od razu (strict).
KNOWN_UNTIL = date(2026, 10, 29)
KNOWN: dict[tuple[str, str, str], str] = {}


def _cases() -> list[Any]:
    return [
        pytest.param(entry, damage, name, id=f"{entry}-{damage}-{name}", marks=_known(entry, damage, name))
        for entry in ENTRIES
        for damage, (kinds, _) in DAMAGES.items()
        for name, (_, kind) in FILES.items()
        if kind in kinds
    ]


def _known(entry: str, damage: str, name: str) -> tuple[pytest.MarkDecorator, ...]:
    reason = KNOWN.get((entry, damage, name))
    if reason is None or datetime.now().astimezone().date() > KNOWN_UNTIL:
        return ()
    return (pytest.mark.xfail(strict=True, reason=reason),)


@pytest.fixture(scope="session")
def world_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("swiat-taty")
    _build(root)
    return root


@pytest.mark.parametrize(("entry", "damage", "name"), _cases())
def test_uszkodzony_plik_nie_konczy_sie_ogolnym_komunikatem(
    world_template: Path, tmp_path: Path, entry: str, damage: str, name: str
) -> None:
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)
    client = _remembering_choices(world)
    target = world.path(name)
    if damage == "ansi" and target.read_text(encoding="utf-8").isascii():
        pytest.skip("ANSI nie zmienia pliku bez polskich znaków")
    DAMAGES[damage][1](target)
    if entry in DIAGNOSIS_ENTRIES:
        world.engines.fail_summary = True
    seen: Seen = []
    try:
        problems = ENTRIES[entry].call(client, seen)
    finally:
        if damage == "bez_odczytu":
            _readable_again(target)
    if damage == "bez_odczytu":
        problems += [f"{where}: niedostępny nazwany uszkodzonym" for where, text in seen if DAMAGED in text]

    assert problems == []


def test_macierz_obejmuje_kazda_operacje_kontraktu_centrum(tmp_path: Path) -> None:
    contract = World(tmp_path).app().openapi()
    operations = {operation["operationId"] for methods in contract["paths"].values() for operation in methods.values()}
    swept = {operation for entry in ENTRIES.values() for operation in entry.operations}

    assert operations - swept - NOT_SWEPT.keys() == set(), "dodaj wejście do ENTRIES albo powód do NOT_SWEPT"
    assert (swept | NOT_SWEPT.keys()) - operations == set(), "ENTRIES albo NOT_SWEPT ma operację spoza kontraktu"


def test_folder_okresow_bez_odczytu_nazywa_folder_w_kazdym_wejsciu(world_template: Path, tmp_path: Path) -> None:
    world = World(tmp_path / "swiat")
    shutil.copytree(world_template, world.root)
    client = _remembering_choices(world)
    periods = world.path("folder_okresow")
    _inaccessible(periods)
    try:
        board = client.get("/api/periods")
        preview = client.post("/api/runs", json={"process": "preparation", "period": PERIOD, "dry_run": True})
        stopped = finished_view(client)["result"]
        world.engines.fail_summary = True
        run_id = _run_with_diagnosis(client, "preparation", PERIOD)
        diagnosis = client.post(f"/api/runs/{run_id}/diagnosis").json()
    finally:
        _readable_again(periods)

    assert board.status_code == 500
    assert "folderu Załączniki" in board.json()["message"]
    assert preview.status_code == 200
    assert stopped["stop_kind"] == "for_tata"
    assert stopped["stops"][0]["what"].startswith("Nie można teraz odczytać folderu.")
    assert stopped["stops"][0]["where"].endswith("Załączniki")
    assert diagnosis["explanation"] == stopped["stops"][0]
