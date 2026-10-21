"""Skrypt dla maszyn: jedno Uruchomienie procesu, wynik jako JSON.

Użycie (z katalogu repozytorium):

    python tools/uruchom_proces.py settlement --source PLIK_ZBIORCZY [--dry-run]
        [--config PLIK] [--worker-template PLIK] [--metrics PLIK]
    python tools/uruchom_proces.py preparation --register REJESTR --periods-directory FOLDER --period TOKEN
        [--dry-run] [--config PLIK] [--internal-template PLIK] [--collective-template PLIK] [--metrics PLIK]

``settlement`` to Przebieg rozliczeń, ``preparation`` Przygotowanie pliku
zbiorczego (klucze procesu z kontraktu Centrum rozliczeń). Proces prowadzi ten
sam rdzeń Uruchomienia procesu co w Centrum, więc wynik ma te same liczby,
etykiety i Komunikaty co karta Uruchomienia. Bez parametru Konfiguracja
wykonawców i Wzorce są te z Centrum (``ConfigurationFiles.default()``), a plik
metryk to plik metryk procesu. Skrypt nie czyta Ustawień taty, nie otwiera okien
wyboru i nie pyta o nic: każdą Decyzję taty odrzuca, więc nigdy nie czeka.

Na stdout trafia jeden obiekt JSON (UTF-8, ``ProcessResult``):

- ``result``: ``OK``, ``WYMAGA_SPRAWDZENIA`` albo ``BLAD_KRYTYCZNY``;
- ``summary``: podsumowanie albo plan (DRY-RUN) z widoku Uruchomienia
  (``contract.RunSummary``), ``null`` przy Zatrzymaniu;
- ``warnings``: ostrzeżenia procesu w zakończonym procesie, każde z kodem i
  trzema częściami Komunikatu;
- ``stop``: przy Zatrzymaniu jego rodzaj (``stop``, ``unexpected``,
  ``after_engine``) i Komunikat z kodem i trzema częściami, inaczej ``null``;
- ``progress``: ostatni stan postępu w kształcie kontraktu (``contract.Progress``);
  po awarii widoku ostatni zbudowany przed nią, a gdy żaden nie powstał, pusty (bez etapów);
- ``total_duration_ms``: ``Czas uruchomienia``;
- ``notices``: ostrzeżenia rdzenia (niezapisane metryki, odłączony podgląd);
- ``metrics_saved``: rekord metryk trafił do pliku metryk.

JSON nie zawiera tekstu wyjątku, śladu wywołań ani linii terminala.

Kod wyjścia to ``Outcome.exit_code``: 0 OK, 2 Wymaga sprawdzenia, 1 Zatrzymanie.
Błędne argumenty też kończą się kodem 1, bez JSON, z opisem użycia na stderr,
żeby literówka nigdy nie wyglądała jak wynik Wymaga sprawdzenia.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import sys
from typing import Literal, NoReturn, TypeVar

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rozliczenia import preparation_process, settlement_process  # noqa: E402
from rozliczenia.centrum import contract, run_view  # noqa: E402
from rozliczenia.centrum.configuration import ConfigurationFiles  # noqa: E402
from rozliczenia.centrum.metrics import MetricsFiles  # noqa: E402
from rozliczenia.decision import Decision  # noqa: E402
from rozliczenia.domain import ProgressEvent  # noqa: E402
from rozliczenia.message import Message  # noqa: E402
from rozliczenia.preparation_process import PreparationInputs  # noqa: E402
from rozliczenia.process_run import Finished, Process, ProcessInputs, run_process  # noqa: E402
from rozliczenia.progress import ProgressSnapshot  # noqa: E402
from rozliczenia.settlement_process import SettlementInputs  # noqa: E402

InputsT = TypeVar("InputsT", bound=ProcessInputs)
SummaryT = TypeVar("SummaryT")

class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CodedMessage(_Model):
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, message: Message) -> CodedMessage:
        return cls(code=message.code, **contract.Message.of(message).model_dump())


class StopResult(_Model):
    kind: Literal["stop", "unexpected", "after_engine"]
    message: CodedMessage


class ProcessResult(_Model):
    result: contract.RunResult
    summary: contract.RunSummary | None
    warnings: list[CodedMessage]
    stop: StopResult | None
    progress: contract.Progress
    total_duration_ms: int
    notices: list[str]
    metrics_saved: bool


class _Unattended:
    continue_hint = "uruchom proces w Centrum rozliczeń i przy decyzji wybierz „Kontynuuj”"

    def __init__(self, progress_view: Callable[[ProgressSnapshot], contract.Progress]) -> None:
        self._progress_view = progress_view
        self.progress = contract.Progress(
            phases=[], template_total=0, templates_completed=0, current_worker=None, figures=[]
        )

    def confirm(self, decision: Decision) -> bool:
        return False

    def start_progress(self, snapshot: ProgressSnapshot) -> None:
        self._show(snapshot)

    def show_progress(self, snapshot: ProgressSnapshot, event: ProgressEvent) -> None:
        self._show(snapshot)

    def stop_progress(self) -> None:
        pass

    def _show(self, snapshot: ProgressSnapshot) -> None:
        self.progress = self._progress_view(snapshot)


def _conduct(
    process: Process[InputsT, SummaryT],
    view: run_view.ProcessView[InputsT, SummaryT],
    inputs: InputsT,
    metrics: Path,
) -> tuple[ProcessResult, int]:
    dry_run = inputs.dry_run
    unattended = _Unattended(lambda snapshot: view.progress(snapshot, dry_run=dry_run))

    def finished_view(inputs: InputsT, summary: SummaryT) -> tuple[contract.RunSummary, list[CodedMessage]]:
        return view.summary(summary, dry_run=dry_run), [CodedMessage.of(warning) for warning in view.warnings(inputs, summary)]

    outcome = run_process(process, inputs, unattended, view=finished_view, metrics_path=metrics)
    summary, coded_warnings = outcome.view or (None, [])
    ending = outcome.ending
    result = ProcessResult(
        result=outcome.result,
        summary=summary,
        warnings=coded_warnings,
        stop=None if isinstance(ending, Finished) else StopResult(kind=ending.kind, message=CodedMessage.of(ending.message)),
        progress=unattended.progress,
        total_duration_ms=outcome.total_duration_ms,
        notices=list(outcome.notices),
        metrics_saved=outcome.metrics_saved,
    )
    return result, outcome.exit_code


def _settle(args: argparse.Namespace) -> tuple[ProcessResult, int]:
    inputs = SettlementInputs(
        args.source, dry_run=args.dry_run, config_path=args.config, worker_template_path=args.worker_template
    )
    return _conduct(settlement_process.PROCESS, run_view.SETTLEMENT, inputs, args.metrics)


def _prepare(args: argparse.Namespace) -> tuple[ProcessResult, int]:
    inputs = PreparationInputs(
        args.register,
        args.periods_directory,
        args.period,
        dry_run=args.dry_run,
        config_path=args.config,
        internal_template_path=args.internal_template,
        collective_template_path=args.collective_template,
    )
    return _conduct(preparation_process.PROCESS, run_view.PREPARATION, inputs, args.metrics)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    files = ConfigurationFiles.default()
    metrics = MetricsFiles.of_cli()
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    processes = parser.add_subparsers(required=True, metavar="PROCES")

    settlement = processes.add_parser("settlement", help=settlement_process.PROCESS.name)
    settlement.add_argument("--source", type=Path, required=True, help="Plik zbiorczy.")
    settlement.add_argument("--config", type=Path, default=files.worker_config, help="Konfiguracja wykonawców.")
    settlement.add_argument(
        "--worker-template", type=Path, default=files.worker_template, help="Wzorzec rozliczenia pracownika."
    )
    settlement.add_argument("--metrics", type=Path, default=metrics.settlement, help="Plik metryk JSONL.")
    settlement.add_argument("--dry-run", action="store_true", help="Podgląd bez zapisu.")
    settlement.set_defaults(run=_settle)

    preparation = processes.add_parser("preparation", help=preparation_process.PROCESS.name)
    preparation.add_argument("--register", type=Path, required=True, help="Rejestr zleceń.")
    preparation.add_argument("--periods-directory", type=Path, required=True, help="Folder okresów.")
    preparation.add_argument("--period", required=True, help="Token okresu, np. 08_14_09_2026.")
    preparation.add_argument("--config", type=Path, default=files.worker_config, help="Konfiguracja wykonawców.")
    preparation.add_argument(
        "--internal-template", type=Path, default=files.internal_template, help="Wzorzec rozliczenia wewnętrznego."
    )
    preparation.add_argument(
        "--collective-template", type=Path, default=files.collective_template, help="Wzorzec pliku zbiorczego."
    )
    preparation.add_argument("--metrics", type=Path, default=metrics.preparation, help="Plik metryk JSONL.")
    preparation.add_argument("--dry-run", action="store_true", help="Podgląd bez zapisu.")
    preparation.set_defaults(run=_prepare)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run: Callable[[argparse.Namespace], tuple[ProcessResult, int]] = args.run
    result, exit_code = run(args)
    sys.stdout.buffer.write(result.model_dump_json(indent=2).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
