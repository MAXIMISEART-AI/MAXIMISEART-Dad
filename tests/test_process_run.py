"""Uruchomienie procesu przez ``run`` na sztucznym procesie w pamięci.

Sztuczny proces jest trzecim adapterem seamu ``Process``, obok Przebiegu
rozliczeń i Przygotowania pliku zbiorczego. Testy CLI obu procesów zostają
przy zachowaniach konkretnego procesu.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import StringIO
import json
from pathlib import Path
import time
from typing import Any, NoReturn, TextIO

import pytest

from rozliczenia.decision import Conversation, Decision
from rozliczenia.domain import ProgressObserver, ProgressPhase
from rozliczenia.message import Message, StopError
from rozliczenia.phase_runner import PhaseRunner
from rozliczenia.plain_progress import PlainProgressAdapter
from rozliczenia.process_run import (
    Finished,
    Process,
    Stop,
    TerminalSummary,
    TerminalView,
    run,
    run_process,
)
from rozliczenia.progress import PhaseState, ProgressNotice, ProgressNoticeKind, ProgressSnapshot
from rozliczenia.rich_progress import RichProgressAdapter
from rozliczenia.telemetry import MetricsStore
from rozliczenia.terminal_conversation import TerminalConversation

from tests.rich_fakes import TtyOutput, install_fake_rich, live_starts_and_stops

PERIOD = "08_14_09_2026"
COUNTERS = frozenset({"items"})
DETACHED_OBSERVER_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."
METRICS_WARNING = "Ostrzeżenie: Nie zapisano metryk; Proces testowy zakończył się niezależnie."
SECRET = "sekret klienta SYN-001"
# Komunikaty zakończeń sztucznego procesu: każde zatrzymanie bez własnego Komunikatu procesu dostaje jeden z nich.
ENDINGS = {
    "unexpected_failure": Message("BLAD_NIEOCZEKIWANY", "Wystąpił nieoczekiwany błąd.", "Proces testowy", "Uruchom ponownie."),
    "plan_not_shown": Message("BLAD_PLANU", "Nie udało się pokazać planu.", "Proces testowy", "Zgłoś to."),
    "summary_not_shown": Message("BLAD_PODSUMOWANIA", "Nie udało się pokazać podsumowania.", "Proces testowy", "Zgłoś to."),
}

Durations = Mapping[ProgressPhase, int]


@dataclass(frozen=True)
class Inputs:
    period: str = PERIOD
    dry_run: bool = False


def stop_error(
    what: str, where: str = "Proces testowy", action: str = "Uruchom ponownie.", *, terminal_line: str | None = None
) -> StopError:
    """Własne zatrzymanie sztucznego procesu z Komunikatem, opcjonalnie z linią terminala."""

    return StopError(Message(code="ZATRZYMANIE", what=what, where=where, action=action, terminal_line=terminal_line))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--metrics", type=Path)
    result.add_argument("--dry-run", action="store_true")
    return result


def gather(args: argparse.Namespace, _conversation: TerminalConversation) -> Inputs:
    return Inputs(dry_run=args.dry_run)


def all_phases(observer: ProgressObserver, before_save: Callable[[], None] = lambda: None) -> Durations:
    phases = PhaseRunner(observer)
    phases.check(lambda: None)
    phases.read(lambda: None)
    phases.plan(lambda: None)
    before_save()
    phases.save(lambda: None)
    return phases.durations_ms()


def execute(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> Durations:
    return all_phases(observer)


def finished_with(result: str) -> Callable[[Durations], Finished]:
    def finished(durations: Durations) -> Finished:
        return Finished(
            result=result,  # type: ignore[arg-type]  # parametr testu: "OK" albo "WYMAGA_SPRAWDZENIA"
            counters={"items": 1},
            phase_durations_ms=durations,
        )

    return finished


def fail(*_args: object) -> NoReturn:
    raise RuntimeError(SECRET)


def terminal_summary(_inputs: Inputs, _durations: Durations) -> TerminalSummary:
    return TerminalSummary(status_lines=["Status: gotowe"], summary_lines=["Podsumowanie: 1 element"])


def stop_lines(stop: Stop) -> Sequence[str]:
    return [f"Zatrzymano: {stop.kind}", *stop.message.terminal_lines]


TERMINAL = TerminalView(summary=terminal_summary, stop=stop_lines)
# Podsumowanie, którego terminal nie umie pokazać: wyjątek w widoku rozmówcy.
UNPRINTABLE: TerminalView[Inputs, Durations] = TerminalView(summary=fail, stop=stop_lines)


def fake_process(**overrides: Any) -> Process[Inputs, Durations]:
    fields: dict[str, Any] = {
        "title": "Proces testowy",
        "shows_templates": False,
        "parser": parser,
        "counter_names": COUNTERS,
        "metrics_failure_tail": "Proces testowy zakończył się niezależnie.",
        "gather": gather,
        "execute": execute,
        "finished": finished_with("OK"),
        **ENDINGS,
    }
    fields.update(overrides)
    return Process(**fields)


def run_fake(
    process: Process[Inputs, Durations],
    metrics_path: Path,
    *args: str,
    output: TextIO | None = None,
    input_stream: TextIO | None = None,
    terminal: TerminalView[Inputs, Durations] = TERMINAL,
) -> tuple[int, str]:
    output = output or StringIO()
    exit_code = run(
        process, terminal, list(args), output=output, input_stream=input_stream, metrics_path=metrics_path
    )
    return exit_code, output.getvalue() if isinstance(output, StringIO) else ""


def records(metrics_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]


def append_completed_records(metrics_path: Path, mode: str, total_duration_ms: int, count: int = 5) -> None:
    phases = {"Sprawdzanie": 1000, "Odczyt danych": 2000, "Planowanie": 3000, "Zapisywanie": 4000}
    for sample in range(count):
        MetricsStore(metrics_path, COUNTERS).append(
            {
                "schema_version": 1,
                "started_at": f"2026-09-28T00:00:0{sample}+00:00",
                "mode": mode,
                "period": PERIOD,
                "completed": True,
                "result": "OK",
                "total_duration_ms": total_duration_ms,
                "phase_durations_ms": phases,
                "counters": {"items": 1},
            }
        )


def failing_at(failing: str) -> tuple[Process[Inputs, Durations], TerminalView[Inputs, Durations]]:
    """Sztuczny proces z wyjątkiem w ``gather``, ``execute``, ``finished`` albo w widoku podsumowania terminala."""

    if failing == "summary":
        return fake_process(), UNPRINTABLE
    return fake_process(**{failing: fail}), TERMINAL


@pytest.mark.parametrize(
    ("failing", "kind"),
    [("gather", "unexpected"), ("execute", "unexpected"), ("finished", "after_engine"), ("summary", "after_engine")],
)
def test_exception_text_never_reaches_tata(tmp_path: Path, failing: str, kind: str) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    process, terminal = failing_at(failing)

    exit_code, output = run_fake(process, metrics_path, terminal=terminal)

    assert exit_code == 1
    assert SECRET not in output
    assert "RuntimeError" not in output
    assert "Traceback" not in output
    lines = output.splitlines()
    assert lines[lines.index(f"Zatrzymano: {kind}") + 4].startswith("Czas uruchomienia: ")
    [record] = records(metrics_path)
    assert (record["completed"], record["result"], record["counters"]) == (False, "BLAD_KRYTYCZNY", {"items": 0})


@pytest.mark.parametrize(
    ("failing", "kind", "ending"),
    [
        ("gather", "unexpected", "unexpected_failure"),
        ("execute", "unexpected", "unexpected_failure"),
        ("finished", "after_engine", "summary_not_shown"),
        ("summary", "after_engine", "summary_not_shown"),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
def test_every_ending_without_own_stop_shows_the_process_ending_message(
    tmp_path: Path, failing: str, kind: str, ending: str, dry_run: bool
) -> None:
    expected = ENDINGS["plan_not_shown" if dry_run and ending == "summary_not_shown" else ending]

    process, terminal = failing_at(failing)

    _, output = run_fake(process, tmp_path / "metrics.jsonl", *(["--dry-run"] if dry_run else []), terminal=terminal)

    lines = output.splitlines()
    stop = lines.index(f"Zatrzymano: {kind}")
    assert lines[stop + 1 : stop + 4] == expected.text.splitlines()


@pytest.mark.parametrize("dry_run", [False, True], ids=["RUN", "DRY-RUN"])
def test_core_closes_every_ending_with_a_message(tmp_path: Path, dry_run: bool) -> None:
    own = stop_error("Brak pliku.")

    def stop_in_engine(_inputs: Inputs, _observer: ProgressObserver, _conversation: Conversation) -> NoReturn:
        raise own

    def view(_inputs: Inputs, durations: Durations) -> Durations:
        return durations

    endings: dict[str, tuple[Process[Inputs, Durations], Callable[[Inputs, Durations], Durations]]] = {
        "stop": (fake_process(execute=stop_in_engine), view),
        "unexpected": (fake_process(execute=fail), view),
        "after_engine": (fake_process(finished=fail), view),
        "view": (fake_process(), fail),
    }
    terminal = TerminalConversation(StringIO(), StringIO())

    seen = {
        name: run_process(
            process, Inputs(dry_run=dry_run), terminal, view=view, metrics_path=tmp_path / "metrics.jsonl"
        )
        for name, (process, view) in endings.items()
    }

    not_shown = ENDINGS["plan_not_shown" if dry_run else "summary_not_shown"]
    assert {
        name: (outcome.ending.kind, outcome.ending.message, outcome.view)
        for name, outcome in seen.items()
        if isinstance(outcome.ending, Stop)
    } == {
        "stop": ("stop", own.message, None),
        "unexpected": ("unexpected", ENDINGS["unexpected_failure"], None),
        "after_engine": ("after_engine", not_shown, None),
        "view": ("after_engine", not_shown, None),
    }
    assert [record["result"] for record in records(tmp_path / "metrics.jsonl")] == ["BLAD_KRYTYCZNY"] * 4


@pytest.mark.parametrize(
    ("error", "expected_lines"),
    [
        (
            stop_error("Brak pliku.", "folder Dane", "Wybierz plik."),
            ["Co się stało: Brak pliku.", "Gdzie: folder Dane", "Co zrobić: Wybierz plik."],
        ),
        (
            stop_error("Brak pliku.", "folder Dane", "Wybierz plik.", terminal_line="Nie znaleziono pliku dane.xlsx."),
            ["Nie znaleziono pliku dane.xlsx."],
        ),
    ],
    ids=["trzy-czesci", "linia-terminala"],
)
def test_own_stop_of_the_process_shows_its_terminal_lines(
    tmp_path: Path, error: StopError, expected_lines: list[str]
) -> None:
    def stop_in_engine(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> Durations:
        phases = PhaseRunner(observer)
        phases.check(lambda: None)

        def read() -> None:
            raise error

        phases.read(read)
        raise AssertionError("Odczyt danych miał zatrzymać proces.")

    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_fake(fake_process(execute=stop_in_engine), metrics_path)

    assert exit_code == 1
    lines = output.splitlines()
    stop = lines.index("Zatrzymano: stop")
    assert lines[stop - 1] == "Etap przerwany: Odczyt danych"
    assert lines[stop + 1 : stop + 1 + len(expected_lines)] == expected_lines
    assert lines[stop + 1 + len(expected_lines)].startswith("Czas uruchomienia: ")
    [record] = records(metrics_path)
    assert record["period"] == PERIOD
    assert record["phase_durations_ms"]["Zapisywanie"] == 0
    assert set(record["phase_durations_ms"]) == {"Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"}


def test_stop_before_engine_start_has_unknown_period_and_shows_statistics(tmp_path: Path) -> None:
    def cancelled(_args: argparse.Namespace, conversation: TerminalConversation) -> Inputs:
        conversation.say("Okno wyboru zostało zamknięte.")
        raise stop_error("Nie wybrano pliku.", terminal_line="Nie wybrano pliku.")

    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "RUN", 1000)

    exit_code, output = run_fake(fake_process(gather=cancelled), metrics_path)

    assert exit_code == 1
    lines = output.splitlines()
    assert lines[:5] == [
        "Okno wyboru zostało zamknięte.",
        "Proces testowy | okres: nieznany | tryb: RUN",
        "Status: uruchomiono",
        "Zatrzymano: stop",
        "Nie wybrano pliku.",
    ]
    assert lines[5].startswith("Czas uruchomienia: ")
    assert lines[6] == "Statystyki RUN | próbek: 5"
    record = MetricsStore(metrics_path, COUNTERS).read()[-1]
    assert (record["period"], record["completed"], record["result"]) == ("nieznany", False, "BLAD_KRYTYCZNY")


@pytest.mark.parametrize(("result", "expected_exit_code"), [("OK", 0), ("WYMAGA_SPRAWDZENIA", 2)])
def test_exit_code_follows_the_result(tmp_path: Path, result: str, expected_exit_code: int) -> None:
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, _ = run_fake(fake_process(finished=finished_with(result)), metrics_path)

    assert exit_code == expected_exit_code
    [record] = records(metrics_path)
    assert (record["completed"], record["result"], record["counters"]) == (True, result, {"items": 1})


@pytest.mark.parametrize("interrupted", [False, True], ids=["sukces", "przerwanie"])
def test_final_lines_are_status_czas_summary_statistics_and_one_detached_observer_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    monkeypatch.setattr(PlainProgressAdapter, "update", fail)
    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "RUN", 1000)
    exit_code, output = run_fake(fake_process(), metrics_path, terminal=UNPRINTABLE if interrupted else TERMINAL)

    assert exit_code == (1 if interrupted else 0)
    lines = output.splitlines()
    expected_status = (
        ["Zatrzymano: after_engine", *ENDINGS["summary_not_shown"].text.splitlines()] if interrupted else ["Status: gotowe"]
    )
    expected_summary = [] if interrupted else ["Podsumowanie: 1 element"]
    status = lines.index(expected_status[0])
    czas = status + len(expected_status)
    assert lines[status:czas] == expected_status
    assert lines[czas].startswith("Czas uruchomienia: ")
    assert lines[czas + 1 : czas + 1 + len(expected_summary)] == expected_summary
    statistics = czas + 1 + len(expected_summary)
    assert lines[statistics] == f"Statystyki RUN | próbek: {5 if interrupted else 6}"
    assert lines[statistics + 1].startswith("całe uruchomienie | P50: ")
    assert lines[-1] == DETACHED_OBSERVER_NOTICE
    assert output.count(DETACHED_OBSERVER_NOTICE) == 1
    assert SECRET not in output


class SlowAnswer(StringIO):
    """Tata odpowiada po chwili namysłu."""

    def readline(self, size: int | None = -1, /) -> str:  # type: ignore[override]  # typeshed: _IOBase -> bytes
        time.sleep(1.0)
        return super().readline()


QUESTION = Decision(
    title="Ostrzeżenie: pytanie",
    message=Message("PYTANIE", "Dane mogą być niepełne.", "Proces testowy", "Sprawdź liczby."),
    counts_title="Elementy",
    counts=[("pierwszy", 1)],
    question="Kontynuować?",
)


def asking_between_planning_and_saving(
    _inputs: Inputs, observer: ProgressObserver, conversation: Conversation
) -> Durations:
    def ask() -> None:
        if not conversation.confirm(QUESTION):
            raise stop_error("Przerwano zgodnie z odpowiedzią.", terminal_line="Przerwano zgodnie z odpowiedzią.")

    return all_phases(observer, before_save=ask)


def test_time_of_decyzja_taty_is_not_counted_in_czas_uruchomienia(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code, output = run_fake(
        fake_process(execute=asking_between_planning_and_saving), metrics_path, input_stream=SlowAnswer("t\n")
    )

    assert exit_code == 0
    reported = next(line for line in output.splitlines() if line.startswith("Czas uruchomienia: "))
    assert int(reported.removeprefix("Czas uruchomienia: ").removesuffix(" ms")) < 1000
    [record] = records(metrics_path)
    assert record["total_duration_ms"] < 1000


def test_answer_from_a_file_is_followed_by_a_new_line(tmp_path: Path) -> None:
    _, output = run_fake(
        fake_process(execute=asking_between_planning_and_saving),
        tmp_path / "metrics.jsonl",
        input_stream=StringIO("t\n"),
    )

    lines = output.splitlines()
    assert lines[lines.index("- pierwszy: 1") + 1] == "Kontynuować? Wpisz t (tak) albo n (nie): "


@pytest.mark.parametrize(
    ("answer", "expected_live_log"),
    [("t\n", ["start", "stop", "start", "stop"]), ("n\n", ["start", "stop"])],
    ids=["zgoda", "odmowa"],
)
def test_live_view_resumes_after_decyzja_taty_only_after_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str, expected_live_log: list[str]
) -> None:
    live_log = install_fake_rich(monkeypatch)

    exit_code, _ = run_fake(
        fake_process(execute=asking_between_planning_and_saving),
        tmp_path / "metrics.jsonl",
        output=TtyOutput(),
        input_stream=StringIO(answer),
    )

    assert exit_code == (0 if answer == "t\n" else 1)
    assert live_starts_and_stops(live_log) == expected_live_log


def test_interrupt_by_tata_stops_live_view_and_passes_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_log = install_fake_rich(monkeypatch)

    def interrupted(_inputs: Inputs, _observer: ProgressObserver, _conversation: Conversation) -> NoReturn:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(fake_process(execute=interrupted), TERMINAL, [], output=TtyOutput(), metrics_path=tmp_path / "metrics.jsonl")

    assert live_log[-1] == "stop"


def test_metrics_write_failure_is_only_a_warning_with_the_process_tail(tmp_path: Path) -> None:
    metrics_parent = tmp_path / "not-a-directory"
    metrics_parent.write_text("nie katalog", encoding="utf-8")

    exit_code, output = run_fake(fake_process(), metrics_parent / "metrics.jsonl")

    assert exit_code == 0
    lines = output.splitlines()
    assert lines[lines.index("Status: gotowe") + 3] == METRICS_WARNING
    assert lines[-1] == METRICS_WARNING


def test_malformed_history_does_not_change_the_result(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "DRY-RUN", 1000)
    with metrics_path.open("a", encoding="utf-8") as stream:
        stream.write('{"schema_version":1,"mode":"DRY-RUN","completed":true,"total_duration_ms":"x"}\n')
        stream.write('{"schema_version":1,"mode":[],"completed":true,"total_duration_ms":1}\n')

    exit_code, output = run_fake(fake_process(), metrics_path, "--dry-run")

    assert exit_code == 0
    assert "Statystyki DRY-RUN | próbek: 6" in output


def test_statistics_report_both_modes_and_every_phase(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    append_completed_records(metrics_path, "RUN", 100_000)
    append_completed_records(metrics_path, "DRY-RUN", 200_000)

    _, output = run_fake(fake_process(), metrics_path, "--dry-run")

    lines = output.splitlines()
    run_statistics = lines.index("Statystyki RUN | próbek: 5")
    assert lines[run_statistics + 1 : run_statistics + 6] == [
        "całe uruchomienie | P50: 100000 ms | P95: 100000 ms",
        "Sprawdzanie | P50: 1000 ms | P95: 1000 ms",
        "Odczyt danych | P50: 2000 ms | P95: 2000 ms",
        "Planowanie | P50: 3000 ms | P95: 3000 ms",
        "Zapisywanie | P50: 4000 ms | P95: 4000 ms",
    ]
    assert lines[run_statistics + 6] == "Statystyki DRY-RUN | próbek: 6"
    assert lines[run_statistics + 7].startswith("całe uruchomienie | P50: ")


@pytest.mark.parametrize("fail_at_write", [1, 4])
def test_terminal_output_failure_does_not_change_result_metrics_or_exit_code(
    tmp_path: Path, fail_at_write: int
) -> None:
    class FailingOutput(StringIO):
        writes = 0

        def write(self, value: str) -> int:
            self.writes += 1
            if self.writes >= fail_at_write:
                raise OSError("synthetic output failure")
            return super().write(value)

    metrics_path = tmp_path / "metrics.jsonl"
    saved: list[str] = []

    def execute_and_save(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> Durations:
        durations = all_phases(observer)
        saved.append("zapisano")
        return durations

    exit_code, _ = run_fake(fake_process(execute=execute_and_save), metrics_path, output=FailingOutput())

    assert exit_code == 0
    assert saved == ["zapisano"]
    [record] = records(metrics_path)
    assert (record["completed"], record["result"]) == (True, "OK")


def test_live_view_refreshes_only_on_zdarzenie_przebiegu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_log = install_fake_rich(monkeypatch)
    renders: list[tuple[ProgressSnapshot, ProgressNotice | None]] = []
    original_render = RichProgressAdapter.render

    def record_render(adapter: RichProgressAdapter, snapshot: ProgressSnapshot, notice: ProgressNotice | None = None) -> Any:
        renders.append((snapshot, notice))
        return original_render(adapter, snapshot, notice)

    monkeypatch.setattr(RichProgressAdapter, "render", record_render)

    def check_only(_inputs: Inputs, observer: ProgressObserver, _conversation: Conversation) -> Durations:
        phases = PhaseRunner(observer)
        phases.check(lambda: None)
        return phases.durations_ms()

    run_fake(fake_process(execute=check_only), tmp_path / "metrics.jsonl", output=TtyOutput())

    assert live_log[:2] == ["auto_refresh=False", "start"]
    assert live_log.count("update refresh=True") == 2
    first_snapshot, first_notice = renders[0]
    assert first_notice is None
    assert first_snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.PENDING
    started_snapshot, started_notice = renders[1]
    assert started_notice is not None and started_notice.kind is ProgressNoticeKind.PHASE_STARTED
    assert started_snapshot.phase_states[ProgressPhase.CHECKING] is PhaseState.RUNNING


def test_rich_failure_falls_back_to_plain_lines_without_changing_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_rich(monkeypatch)
    render_calls = 0
    original_render = RichProgressAdapter.render

    def fail_on_first_refresh(
        adapter: RichProgressAdapter, snapshot: ProgressSnapshot, notice: ProgressNotice | None = None
    ) -> Any:
        nonlocal render_calls
        render_calls += 1
        if render_calls == 2:
            raise RuntimeError("synthetic Rich rendering failure")
        return original_render(adapter, snapshot, notice)

    monkeypatch.setattr(RichProgressAdapter, "render", fail_on_first_refresh)
    output = TtyOutput()
    metrics_path = tmp_path / "metrics.jsonl"

    exit_code = run(fake_process(), TERMINAL, [], output=output, metrics_path=metrics_path)

    assert exit_code == 0
    lines = output.getvalue().splitlines()
    assert "Etap: Odczyt danych" in lines
    assert "Etap: Zapisywanie" in lines
    assert "synthetic Rich rendering failure" not in output.getvalue()
    assert DETACHED_OBSERVER_NOTICE not in output.getvalue()
    [record] = records(metrics_path)
    assert record["result"] == "OK"
