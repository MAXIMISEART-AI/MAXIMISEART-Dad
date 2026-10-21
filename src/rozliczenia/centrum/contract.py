"""Kontrakt serwer ↔ przeglądarka: modele odpowiedzi i żądań Centrum rozliczeń.

Z tych modeli powstaje OpenAPI, a z niego schematy zod i typy w
``frontend/src/api/generated`` (``npm run contract`` w ``frontend/``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from rozliczenia.message import Message as ProcessMessage
from rozliczenia.period_folder import PeriodStatus


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Problem(_Model):
    """Odmowa wykonania żądania z bezpiecznym komunikatem dla taty, bez tekstu wyjątku."""

    message: str


class Refusal(Exception):
    """Serwer odmawia żądania; ``create_app`` zamienia odmowę na odpowiedź ``Problem``."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Odmowy akcji na zasobie w OpenAPI: brak zasobu (404) albo zły stan (409), obie jako ``Problem``.
NOT_FOUND_OR_CONFLICT: dict[int | str, dict[str, object]] = {404: {"model": Problem}, 409: {"model": Problem}}


class Health(_Model):
    """Tożsamość działającego Centrum.

    ``commit`` to pełny commit narzędzia (``None`` poza klonem Gita), ``instance`` losowy identyfikator tego
    startu Centrum: po ponownym starcie jest inny, także gdy commit się nie zmienił.
    """

    service: Literal["centrum-rozliczen"]
    version: str
    commit: str | None
    instance: str


class Closing(_Model):
    """Centrum przyjęło prośbę o zamknięcie i kończy pracę po tej odpowiedzi."""

    state: Literal["closing"]


class NotSetPath(_Model):
    """Ścieżka jeszcze niewskazana albo plik ustawień nieczytelny."""

    state: Literal["not_set"]


class MissingPath(_Model):
    """Zapamiętana ścieżka, pod którą nie ma już pliku albo folderu."""

    state: Literal["missing"]
    path: str
    name: str


class ReadyPath(_Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[NotSetPath | MissingPath | ReadyPath, Field(discriminator="state")]
Theme = Literal["dark", "light"]


class Settings(_Model):
    order_register: PathSetting
    periods_directory: PathSetting
    theme: Theme


class Choice(_Model):
    """Ustawienia po natywnym oknie wyboru: wybór zapisuje ścieżkę, anulowanie niczego nie zmienia."""

    settings: Settings


class ThemeChange(_Model):
    theme: Theme


class ProcessStep(_Model):
    """Następny krok okresu robi proces; ``preview_hint`` to podpowiedź „Podgląd bez zapisu” tego procesu."""

    action: Literal["prepare_collective_file", "create_worker_settlements"]
    label: str
    hint: str
    preview_hint: str


class ClosedStep(_Model):
    """Okres jest zamknięty: następnego kroku nie robi żaden proces."""

    action: Literal["none"]
    label: str
    hint: str


NextStep = Annotated[ProcessStep | ClosedStep, Field(discriminator="action")]


class PeriodRow(_Model):
    """Jeden okres Tablicy okresów, wyliczony z plików przy każdym odczycie."""

    token: str
    tuesday: date
    monday: date
    status: PeriodStatus
    status_label: str
    period_folder_exists: bool
    internal_settlement_exists: bool
    collective_file_exists: bool
    worker_settlements_folder_exists: bool
    worker_settlement_count: int
    last_complete: bool
    next_step: NextStep


class BoardNotSet(_Model):
    state: Literal["not_set"]


class BoardMissing(_Model):
    state: Literal["missing"]
    name: str


class BoardReady(_Model):
    """Okresy od najnowszego; ``last_prepared_period`` to najnowszy okres z Plikiem zbiorczym."""

    state: Literal["ready"]
    periods: list[PeriodRow]
    last_prepared_period: str | None


PeriodBoard = Annotated[BoardNotSet | BoardMissing | BoardReady, Field(discriminator="state")]

OpenTarget = Literal["internal_settlement", "collective_file", "period_folder", "worker_settlements_folder"]


class OpenRequest(_Model):
    """Co otworzyć w okresie; ścieżkę wylicza serwer z folderu okresów, nigdy z żądania."""

    target: OpenTarget


class Opened(_Model):
    name: str


# Każdy proces ma klucz, ten sam w Uruchomieniach i w Metrykach.
ProcessKey = Literal["preparation", "settlement"]
RunMode = Literal["RUN", "DRY-RUN"]
RunResult = Literal["OK", "WYMAGA_SPRAWDZENIA", "BLAD_KRYTYCZNY"]


class PhaseDuration(_Model):
    phase: str
    duration_ms: int


class ProcessRun(_Model):
    """Jedno Uruchomienie procesu z pliku metryk; ``BLAD_KRYTYCZNY`` to przerwane, z czasami etapów do przerwania.

    ``origin`` mówi, skąd wystartowało: ``cmd`` to launcher (CLI), ``centrum`` to Centrum rozliczeń.
    """

    process: ProcessKey
    process_label: str
    started_at: datetime
    mode: RunMode
    period: str
    result: RunResult
    total_duration_ms: int
    phase_durations: list[PhaseDuration]
    origin: Literal["cmd", "centrum"]


class PhasePercentiles(_Model):
    phase: str
    p50_ms: int
    p95_ms: int


class Percentiles(_Model):
    """P50 i P95 czasu całego Uruchomienia procesu i każdego etapu, w milisekundach."""

    p50_ms: int
    p95_ms: int
    phases: list[PhasePercentiles]


class ResultCounts(_Model):
    ok: int
    needs_review: int
    critical: int


class ModeStatistics(_Model):
    """Statystyki jednego procesu w jednym trybie; bez ``percentiles`` poniżej minimum ukończonych obserwacji."""

    process: ProcessKey
    mode: RunMode
    completed_runs: int
    percentiles: Percentiles | None
    results: ResultCounts


class RecentResults(_Model):
    """Wyniki Uruchomień procesu obu procesów z ostatnich ``weeks`` tygodni."""

    weeks: int
    results: ResultCounts


class Metrics(_Model):
    """Historia Uruchomień procesu z obu plików metryk, czytanych przy każdym odczycie, od najnowszego."""

    phases: list[str]
    minimum_completed_runs: int
    runs: list[ProcessRun]
    statistics: list[ModeStatistics]
    recent: RecentResults


# Uruchomienia procesu.
PhaseName = Literal["Sprawdzanie", "Odczyt danych", "Planowanie", "Zapisywanie"]


class PeriodChoice(_Model):
    """Okres do wyboru przy starcie, ze Statusem okresu wyliczonym z plików."""

    token: str
    tuesday: date
    monday: date
    status_label: str
    last_complete: bool
    # W historii metryk jest udany podgląd bez zapisu tego procesu i okresu (z Centrum albo z ``.cmd``).
    previewed: bool
    # Nazwa Pliku zbiorczego okresu, gdy proces go czyta (Przebieg rozliczeń); tata go nie wskazuje.
    collective_file: str | None


class ProcessSetup(_Model):
    """Co tata wybiera przed Uruchomieniem procesu; ``blocker`` mówi, czego jeszcze brakuje w ustawieniach.

    ``reminder``, ``confirms_readiness`` i ``preview_hint`` deklaruje proces: przypomnienie przed
    uruchomieniem, czy „Uruchom” potwierdza Gotowość, i podpowiedź „Podgląd bez zapisu”.
    """

    process: ProcessKey
    title: str
    creates: str
    reminder: str
    confirms_readiness: bool
    preview_hint: str
    periods: list[PeriodChoice]
    preselected_period: str
    blocker: str | None


class RunSetup(_Model):
    processes: list[ProcessSetup]


class RunRequest(_Model):
    """Start Uruchomienia procesu; pliki wejściowe wylicza serwer z ustawień i okresu."""

    process: ProcessKey
    period: str
    dry_run: bool


class PhaseProgress(_Model):
    phase: PhaseName
    state: Literal["pending", "running", "completed", "failed"]
    duration_ms: int


class Figure(_Model):
    """Liczba karty Uruchomienia z etykietą; ``unit`` ``ms`` to czas, który przeglądarka pokazuje w sekundach."""

    label: str
    value: int
    unit: Literal["count", "ms"]


class Progress(_Model):
    """Wyświetlany podzbiór snapshotu jedynej projekcji postępu (ADR 0002): etapy, Szablony pracowników i liczby."""

    phases: list[PhaseProgress]
    template_total: int
    templates_completed: int
    current_worker: str | None
    figures: list[Figure]


class RunInfo(_Model):
    """Uruchomienie procesu; ``confirms_readiness`` deklaruje proces: „Uruchom” potwierdza Gotowość."""

    id: str
    process: ProcessKey
    title: str
    period: str
    dry_run: bool
    confirms_readiness: bool


class Message(_Model):
    """Komunikat w trzech częściach (Co się stało, Gdzie, Co zrobić), ta sama treść co w terminalu."""

    what: str
    where: str
    action: str

    @classmethod
    def of(cls, message: ProcessMessage) -> Message:
        """Tylko trzy części Komunikatu; ``terminal_line`` nie trafia do Centrum, bo może mieć pełną ścieżkę."""

        return cls(what=message.what, where=message.where, action=message.action)


class Count(_Model):
    label: str
    count: int


class CountGroup(_Model):
    title: str
    counts: list[Count]


class Decision(_Model):
    """Pytanie do taty z części decyzji procesu: tytuł, komunikat w trzech częściach i liczby (np. Zlecenia na dzień)."""

    question: str
    title: str
    message: Message
    counts: CountGroup


class PeriodFile(_Model):
    """Plik okresu z wyniku, sama nazwa: Rozliczenie wewnętrzne albo Plik zbiorczy."""

    name: str
    kind: Literal["internal_settlement", "collective_file"]


class WorkerFile(_Model):
    """Wiersz planu plików: nazwa pliku Szablonu pracownika i liczba Wierszy danych (0 = pusty skoroszyt)."""

    file: str
    rows: int


class RunSummary(_Model):
    """Podsumowanie albo plan (DRY-RUN) procesu tak, jak pokazuje je karta Uruchomienia, bez danych klientów.

    Liczby wyniku, potem szczegóły: kafelki liczb (np. Zlecenia na dzień), pliki okresu i plan plików
    (``None``, gdy proces go nie ma).
    """

    figures: list[Figure]
    counts: CountGroup | None
    files: list[PeriodFile]
    file_plan: list[WorkerFile] | None


class ReportDraft(_Model):
    """Dokładna treść Zgłoszenia, które „Wyślij do Maksa” wyśle do skrzynki Zgłoszeń: tytuł i treść Markdown."""

    title: str
    body: str


class ReportReady(_Model):
    """Zgłoszenia tego problemu jeszcze nie wysłano; „Wyślij do Maksa” wyśle podgląd z Diagnozy."""

    state: Literal["ready"]


class ReportSent(_Model):
    """Zgłoszenie tego problemu wysłano w tym Uruchomieniu; czeka na naprawę."""

    state: Literal["sent"]


class ReportWaiting(_Model):
    """Zgłoszenie tego problemu wysłano wcześniej i jest otwarte: czeka na naprawę, drugie nie powstaje."""

    state: Literal["waiting"]


class ReportSaved(_Model):
    """Zgłoszenia nie wysłano (brak klucza, odmowa albo brak połączenia); zwykle czeka w pliku na tym komputerze.

    ``message`` mówi, który plik przesłać Maksowi mailem i kiedy spróbować ponownie, a gdy i zapis pliku
    się nie udał (pliku nie ma), że treść trzeba przesłać z podglądu.
    """

    state: Literal["saved"]
    message: Message


ReportState = Annotated[ReportReady | ReportSent | ReportWaiting | ReportSaved, Field(discriminator="state")]


# Rodzaj Zatrzymania: ``for_tata`` usuwa tata sam według Komunikatu, ``for_maks`` każe przekazać Komunikat
# osobie utrzymującej narzędzie (także nieoczekiwany wyjątek), ``repeated`` to ten sam Komunikat „dla taty”
# drugi raz z rzędu w tym samym procesie. Przy ``for_maks`` i ``repeated`` Centrum proponuje Diagnozę.
StopKind = Literal["for_tata", "for_maks", "repeated"]
# Diagnoza przy Zatrzymaniu: ``on_request`` to przycisk „Diagnoza” zamiast następnej akcji, ``automatic`` to
# nieoczekiwany wyjątek, przy którym przeglądarka zaczyna Diagnozę od razu po pokazaniu wyniku.
DiagnosisOffer = Literal["on_request", "automatic"]


class RunOutcome(_Model):
    """Wynik Uruchomienia procesu: zatrzymania i ostrzeżenia w trzech częściach, powiadomienia i podsumowanie.

    ``ending`` mówi, jak się skończyło: ``finished``, własne zatrzymanie procesu (``stop``), nieoczekiwany
    błąd (``unexpected``) albo błąd po zakończeniu silnika (``after_engine``). ``next_action`` to akcja,
    którą Centrum proponuje po wyniku, a ``headline`` to tytuł banera wyniku. ``stop_kind`` to rodzaj
    Zatrzymania (``None`` bez Zatrzymania), ``diagnosis`` to Diagnoza, którą z niego Centrum proponuje
    (``None``: bez Zatrzymania i przy Zatrzymaniu „dla taty”), a ``report`` stan Zgłoszenia do Maksa tego
    problemu (``None``, gdy Centrum nie proponuje Diagnozy).
    """

    result: RunResult
    headline: str
    ending: Literal["finished", "stop", "unexpected", "after_engine"]
    next_action: Literal["run", "rerun", "open_period_folder"]
    stop_kind: StopKind | None
    diagnosis: DiagnosisOffer | None
    report: ReportState | None
    stops: list[Message]
    warnings: list[Message]
    notices: list[str]
    summary: RunSummary | None


class RunIdle(_Model):
    """Od startu serwera nie było żadnego Uruchomienia procesu."""

    state: Literal["idle"]


class RunRunning(_Model):
    state: Literal["running"]
    run: RunInfo
    progress: Progress
    progress_stale: bool


class RunAwaitingDecision(_Model):
    """Uruchomienie czeka na decyzję taty; czas czekania nie wlicza się do czasu ani do metryk."""

    state: Literal["awaiting_decision"]
    run: RunInfo
    progress: Progress
    decision: Decision


class RunFinished(_Model):
    state: Literal["finished"]
    run: RunInfo
    progress: Progress
    progress_stale: bool
    result: RunOutcome


RunView = Annotated[RunIdle | RunRunning | RunAwaitingDecision | RunFinished, Field(discriminator="state")]


class RunEvent(_Model):
    """Jedno zdarzenie strumienia SSE: kolejny numer i pełny widok bieżącego Uruchomienia procesu."""

    sequence: int
    view: RunView


class DecisionAnswer(_Model):
    answer: Literal["continue", "abort"]


class DiagnosisCheck(_Model):
    """Jedno sprawdzenie Diagnozy: co sprawdzono, czy przeszło i krótko dlaczego, bez pełnych ścieżek."""

    label: str
    state: Literal["passed", "failed", "not_checked"]
    detail: str


class Diagnosis(_Model):
    """Wynik Diagnozy Zatrzymania: wyjaśnienie w trzech częściach i każde sprawdzenie po kolei.

    ``explanation`` to Komunikat pierwszego sprawdzenia, które nie przeszło, albo „Nie znalazłem
    przyczyny na tym komputerze”. ``next_action`` ``rerun``: przyczynę tata usuwa sam i uruchamia
    ponownie; ``report``: przyczynę usuwa Maks. ``report`` to podgląd: dokładnie to Zgłoszenie wyśle
    „Wyślij do Maksa” (przy ``rerun`` jako drugi przycisk). ``confirms_stop``: wyjaśnienie to ten sam
    Komunikat (kod i trzy części) co Zatrzymanie, więc przeglądarka go nie powtarza.
    ``update_proposal``: jest nowsza wersja narzędzia, ale wyjaśnieniem jest inna przyczyna, więc
    Diagnoza proponuje Aktualizację narzędzia tylko pod wyjaśnieniem.
    """

    explanation: Message
    confirms_stop: bool
    next_action: Literal["rerun", "report"]
    update_proposal: bool
    checks: list[DiagnosisCheck]
    report: ReportDraft


class TemplateReady(_Model):
    """Wzorzec jest na miejscu, nie jest otwarty i przechodzi Sprawdzanie."""

    state: Literal["ready"]
    label: str
    file_name: str


TemplateProblemKind = Literal["missing", "open_in_excel", "unreadable"]


class TemplateProblem(_Model):
    """Wzorca nie ma, jest otwarty w Excelu albo nie przechodzi Sprawdzania."""

    state: Literal["problem"]
    label: str
    file_name: str
    problem: TemplateProblemKind
    message: Message


TemplateStatus = Annotated[TemplateReady | TemplateProblem, Field(discriminator="state")]


class WorkersReady(_Model):
    """Nazwy Wykonawców w kolejności z konfiguracji wykonawców."""

    state: Literal["ready"]
    names: list[str]


class WorkersUnreadable(_Model):
    state: Literal["unreadable"]
    message: Message


Workers = Annotated[WorkersReady | WorkersUnreadable, Field(discriminator="state")]


# Klucz do Zgłoszeń na tym komputerze: ``ready`` („Zgłoszenia: gotowe”) albo ``missing_key``; nigdy jego wartość.
ReportKeyState = Literal["ready", "missing_key"]


# Aktualność narzędzia: ``current`` (commit narzędzia to `main` na GitHubie), ``newer`` (jest nowsza wersja),
# ``not_checked`` (brak sieci albo narzędzie bez commitu Gita).
ToolFreshnessState = Literal["current", "newer", "not_checked"]


class Configuration(_Model):
    """Konfiguracja tylko do odczytu, wyliczana z katalogu konfiguracji przy każdym odczycie.

    ``commit`` to pierwsze 7 znaków commitu narzędzia (``None`` poza klonem Gita), ``freshness`` jego
    Aktualność względem `main` na GitHubie, sprawdzana jak w Diagnozie.
    """

    version: str
    commit: str | None
    freshness: ToolFreshnessState
    templates: list[TemplateStatus]
    workers: Workers
    reports: ReportKeyState


# Krok Aktualizacji narzędzia: pobieranie nowej wersji, instalowanie bibliotek, ponowne uruchamianie Centrum.
ToolUpdateStep = Literal["fetching", "installing", "restarting"]


class ToolUpdateIdle(_Model):
    """Od startu Centrum tata nie zlecił Aktualizacji narzędzia."""

    state: Literal["idle"]


class ToolUpdateRunning(_Model):
    state: Literal["running"]
    step: ToolUpdateStep


class ToolUpdateUpToDate(_Model):
    """Narzędzie już było w najnowszej wersji; nic się nie zmieniło."""

    state: Literal["up_to_date"]


class ToolUpdateUpdated(_Model):
    """Narzędzie jest w nowej wersji ``commit`` (pierwsze 7 znaków); to Centrum wystartowało już w niej."""

    state: Literal["updated"]
    commit: str


class ToolUpdateFailed(_Model):
    """Aktualizacja narzędzia się nie udała; narzędzie zostało w wersji sprzed kliknięcia.

    ``next_action`` ``retry``: tata klika „Zaktualizuj narzędzie” jeszcze raz (np. gdy wróci internet);
    ``report``: sprawę przejmuje Maks. ``draft`` to Zgłoszenie z faktami dziennika tej aktualizacji, które
    wyśle „Wyślij do Maksa”, a ``report`` jego stan.
    """

    state: Literal["failed"]
    message: Message
    next_action: Literal["retry", "report"]
    report: ReportState
    draft: ReportDraft


ToolUpdate = Annotated[
    ToolUpdateIdle | ToolUpdateRunning | ToolUpdateUpToDate | ToolUpdateUpdated | ToolUpdateFailed,
    Field(discriminator="state"),
]


class RepairNotice(_Model):
    """Powiadomienie o naprawie na stronie Okresy.

    ``repaired``: Maks zamknął Zgłoszenie wysłane z wersji narzędzia, która nadal
    działa na tym komputerze („Maks naprawił zgłoszony problem. Zaktualizuj narzędzie.”).
    """

    repaired: bool


# Strony z bocznego menu (`frontend/src/pages.tsx`): identyfikator to adres `#/<id>` strony.
PageId = Literal["okresy", "uruchomienia", "metryki", "konfiguracja"]
# Zimny start strony (otwarcie albo odświeżenie karty) albo przejście w menu.
ViewKind = Literal["cold_start", "navigation"]
# Operacje API, które przeglądarka mierzy: nazwy (`operation_id`) zamiast adresu z tokenem okresu. Trasy spoza
# tej listy, każda z powodem, wymienia `OUTSIDE_TIMING` w tools/export_openapi.py, który pilnuje obu stron.
ApiOperation = Literal[
    "getHealth",
    "getSettings",
    "chooseRegister",
    "choosePeriodsDirectory",
    "changeTheme",
    "getPeriodBoard",
    "openPeriodPath",
    "getRunSetup",
    "startRun",
    "decideRun",
    "diagnoseRun",
    "reportRun",
    "getRepairNotice",
    "getMetrics",
    "getConfiguration",
    "startToolUpdate",
    "getToolUpdate",
    "reportToolUpdate",
    "closeCentrum",
]
# Do 10 minut: dłuższy czas to uśpiona karta, nie pomiar.
Milliseconds = Annotated[int, Field(ge=0, le=600_000)]
MAX_TIMED_REQUESTS = 20


class ApiTiming(_Model):
    """Jedno zapytanie API widoku: czas w przeglądarce i czas serwera z ``Server-Timing`` (``None``: brak nagłówka)."""

    operation: ApiOperation
    browser_ms: Milliseconds
    server_ms: Milliseconds | None


class ViewTiming(_Model):
    """Pomiar gotowego widoku z przeglądarki: same liczby i nazwy z kontraktu, bez adresów i treści.

    ``ready_ms`` to czas do gotowej treści, ``fcp_ms`` pierwsze malowanie treści
    (tylko przy zimnym starcie), ``skeleton_ms`` czas widocznego szkieletu.
    """

    kind: ViewKind
    page: PageId
    ready_ms: Milliseconds
    fcp_ms: Milliseconds | None
    skeleton_ms: Milliseconds
    requests: Annotated[list[ApiTiming], Field(max_length=MAX_TIMED_REQUESTS)]
