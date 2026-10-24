import { call } from "@/api/client"
import type {
  DadNoteRequest,
  DadNoteText,
  DecisionAnswer,
  GetCurrentRunResponse,
  GetNotificationsResponse,
  GetPeriodBoardResponse,
  GetToolUpdateResponse,
  NotificationsRead,
  OpenRequest,
  WorkerSettlementRequest,
  PeriodRow,
  RunEvent,
  RunRequest,
  SendDadNoteResponse,
  Settings,
  ThemeChange,
  ViewTiming,
} from "@/api/generated"
import {
  zChangeThemeResponse,
  zCloseCentrumResponse,
  zChoosePeriodsDirectoryResponse,
  zChooseRegisterResponse,
  zDecideRunResponse,
  zDiagnoseRunResponse,
  zDraftDadNoteResponse,
  zGetDadNoteRunsResponse,
  zGetConfigurationResponse,
  zGetHealthResponse,
  zGetMetricsResponse,
  zGetNotificationsResponse,
  zGetPeriodBoardResponse,
  zGetRunSetupResponse,
  zGetSettingsResponse,
  zGetToolUpdateResponse,
  zMarkNotificationsReadResponse,
  zOpenPeriodPathResponse,
  zOpenWorkerSettlementResponse,
  zReportRunResponse,
  zReportToolUpdateResponse,
  zRunEvent,
  zSendDadNoteResponse,
  zStartRunResponse,
  zStartToolUpdateResponse,
} from "@/api/generated/zod.gen"

export type {
  Choice,
  Configuration,
  Count,
  DadNoteDraft,
  DadNoteRequest,
  Decision,
  DecisionAnswer,
  Diagnosis,
  DiagnosisCheck,
  Figure,
  Message,
  Metrics,
  Percentiles,
  OpenRequest,
  PeriodChoice,
  PeriodRow,
  PeriodFile,
  PhaseProgress,
  PinnableRun,
  ProcessRun,
  ProcessStep,
  ProcessSetup,
  Progress,
  ReportDraft,
  ResultCounts,
  RunEvent,
  RunInfo,
  RunOutcome,
  RunRequest,
  RunSummary,
  Settings,
  TemplateProblem,
  WorkerSettlement,
  WorkerSettlementRequest,
} from "@/api/generated"

export type PeriodBoard = GetPeriodBoardResponse

/** Aktualizacja narzędzia: krok albo wynik (unia z kontraktu). */
export type ToolUpdate = GetToolUpdateResponse

/** Następny krok okresu: proces z podpowiedzią podglądu albo okres zamknięty (unia z kontraktu). */
export type NextStep = PeriodRow["next_step"]

export type PathSetting = Settings["order_register"]

export type Theme = ThemeChange["theme"]

export type Process = RunRequest["process"]

export type OpenTarget = OpenRequest["target"]

/** Powiadomienia od najnowszego i liczba nowych (kropka na dzwonku). */
export type Notifications = GetNotificationsResponse

/** Jedno Powiadomienie: Uwaga taty albo Zgłoszenie (unia z kontraktu po `kind`). */
export type Notification = Notifications["items"][number]

/** Uwaga taty po „Wyślij”: skrzynka ją przyjęła albo czeka w kolejce (unia z kontraktu). */
export type DadNoteState = SendDadNoteResponse

/** Widok bieżącego Uruchomienia procesu; jego `state` to stany UI (unia z kontraktu). */
export type RunView = GetCurrentRunResponse

function send(
  method: "POST" | "PUT",
  body?:
    | OpenRequest
    | WorkerSettlementRequest
    | ThemeChange
    | RunRequest
    | DecisionAnswer
    | ViewTiming
    | DadNoteText
    | DadNoteRequest
    | NotificationsRead
): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function getSettings() {
  return call(zGetSettingsResponse, "getSettings", "/api/settings")
}

/** Otwiera natywne okno wyboru na komputerze taty i zapamiętuje wybrany Rejestr zleceń. */
export function chooseOrderRegister() {
  return call(zChooseRegisterResponse, "chooseRegister", "/api/settings/register/choose", send("POST"))
}

/** Otwiera natywne okno wyboru folderu i zapamiętuje folder okresów. */
export function choosePeriodsDirectory() {
  return call(
    zChoosePeriodsDirectoryResponse,
    "choosePeriodsDirectory",
    "/api/settings/periods-directory/choose",
    send("POST")
  )
}

export function changeTheme(theme: Theme) {
  return call(zChangeThemeResponse, "changeTheme", "/api/settings/theme", send("PUT", { theme }))
}

export function getPeriodBoard() {
  return call(zGetPeriodBoardResponse, "getPeriodBoard", "/api/periods")
}

/** Serwer sam wylicza ścieżkę z folderu okresów; przeglądarka podaje tylko okres i rodzaj pliku. */
export function openPeriodPath(token: string, target: OpenTarget) {
  return call(
    zOpenPeriodPathResponse,
    "openPeriodPath",
    `/api/periods/${encodeURIComponent(token)}/open`,
    send("POST", { target })
  )
}

/** Rozliczenie pracownika jednego Wykonawcy; ścieżkę wylicza serwer z Folderu okresu, przeglądarka podaje Wykonawcę. */
export function openWorkerSettlement(token: string, worker: string) {
  return call(
    zOpenWorkerSettlementResponse,
    "openWorkerSettlement",
    `/api/periods/${encodeURIComponent(token)}/worker-settlements/open`,
    send("POST", { worker })
  )
}

/** Co tata wybiera przed Uruchomieniem procesu: procesy, okresy z preselekcją, przypomnienie, brakujące ustawienia. */
export function getRunSetup() {
  return call(zGetRunSetupResponse, "getRunSetup", "/api/runs/setup")
}

/** Start Uruchomienia procesu; gdy trwa już inne, serwer odmawia z bezpiecznym komunikatem. */
export function startRun(request: RunRequest) {
  return call(zStartRunResponse, "startRun", "/api/runs", send("POST", request))
}

/** Decyzja taty o niepełnym okresie dla Uruchomienia `runId`. */
export function decideRun(runId: string, answer: DecisionAnswer["answer"]) {
  return call(
    zDecideRunResponse,
    "decideRun",
    `/api/runs/${encodeURIComponent(runId)}/decision`,
    send("POST", { answer })
  )
}

/** Diagnoza Zatrzymania Uruchomienia `runId`: wyjaśnienie i sprawdzenia; serwer tylko czyta pliki taty. */
export function diagnoseRun(runId: string) {
  return call(zDiagnoseRunResponse, "diagnoseRun", `/api/runs/${encodeURIComponent(runId)}/diagnosis`, send("POST"))
}

/** „Wyślij do Maksa”: serwer wysyła podgląd Zgłoszenia z ostatniej Diagnozy Uruchomienia `runId`. */
export function reportRun(runId: string) {
  return call(zReportRunResponse, "reportRun", `/api/runs/${encodeURIComponent(runId)}/report`, send("POST"))
}

/**
 * Strumień SSE Uruchomień procesu, otwarty tylko w widocznej karcie. Przeglądarka trzyma najwyżej 6 połączeń
 * z Centrum naraz, wspólnie dla wszystkich kart, a każde kliknięcie skrótu otwiera nową kartę: strumienie kart
 * w tle zajęłyby wszystkie połączenia i każde zapytanie Centrum czekałoby bez końca. Karta w tle oddaje więc
 * połączenie, a po powrocie łączy się od nowa. Po połączeniu najpierw przychodzi bieżący widok, potem każda
 * zmiana; po zerwaniu przeglądarka sama łączy się ponownie i znowu dostaje bieżący widok. Każde zdarzenie jest
 * parsowane schematem z kontraktu; zdarzenie, którego nie da się sparsować, jest pomijane.
 */
export function watchRunEvents(
  onEvent: (event: RunEvent) => void,
  onConnection: (connected: boolean) => void
): () => void {
  let source: EventSource | null = null

  const connect = () => {
    const stream = new EventSource("/api/runs/events")

    stream.addEventListener("open", () => onConnection(true))
    stream.addEventListener("error", () => onConnection(false))
    stream.addEventListener("message", (message: MessageEvent<string>) => {
      let data: unknown

      try {
        data = JSON.parse(message.data)
      } catch {
        return
      }

      const parsed = zRunEvent.safeParse(data)

      if (parsed.success) {
        onEvent(parsed.data)
      }
    })

    return stream
  }

  const followVisibility = () => {
    if (document.visibilityState === "visible") {
      source ??= connect()
    } else {
      source?.close()
      source = null
    }
  }

  followVisibility()
  document.addEventListener("visibilitychange", followVisibility)

  return () => {
    document.removeEventListener("visibilitychange", followVisibility)
    source?.close()
  }
}

/** Historia Uruchomień procesu z obu plików metryk, z P50/P95 i rozkładem wyników; serwer czyta pliki przy każdym odczycie. */
export function getMetrics() {
  return call(zGetMetricsResponse, "getMetrics", "/api/metrics")
}

/** Konfiguracja tylko do odczytu: Wzorce, Wykonawcy i wersja narzędzia. */
export function getConfiguration() {
  return call(zGetConfigurationResponse, "getConfiguration", "/api/configuration")
}

/** Aktualizacja narzędzia: serwer odpowiada od razu pierwszym krokiem i aktualizuje w tle; odmawia, gdy coś trwa. */
export function startToolUpdate() {
  return call(zStartToolUpdateResponse, "startToolUpdate", "/api/tool-update", send("POST"))
}

/** Tożsamość Centrum; `instance` jest inny po każdym starcie, więc karta rozpozna po nim Centrum po aktualizacji. */
export function getHealth() {
  return call(zGetHealthResponse, "getHealth", "/api/health")
}

/** Krok trwającej Aktualizacji narzędzia albo jej wynik od startu Centrum. */
export function getToolUpdate() {
  return call(zGetToolUpdateResponse, "getToolUpdate", "/api/tool-update")
}

/** „Wyślij do Maksa” przy nieudanej Aktualizacji narzędzia: serwer wysyła podgląd Zgłoszenia z jej faktami. */
export function reportToolUpdate() {
  return call(zReportToolUpdateResponse, "reportToolUpdate", "/api/tool-update/report", send("POST"))
}

/** Powiadomienia o Uwagach taty i Zgłoszeniach; serwer pyta skrzynkę najwyżej raz na 10 minut, bez sieci po cichu. */
export function getNotifications() {
  return call(zGetNotificationsResponse, "getNotifications", "/api/notifications")
}

/** Tata zobaczył te Powiadomienia (ich `id`); serwer pamięta to także po ponownym starcie Centrum. */
export function markNotificationsRead(ids: ReadonlyArray<string>) {
  return call(
    zMarkNotificationsReadResponse,
    "markNotificationsRead",
    "/api/notifications/read",
    send("POST", { ids: [...ids] })
  )
}

/**
 * Uruchomienia z Centrum, do których tata może przypiąć Uwagę, od najnowszego. `selected` (Uruchomienie, z którego
 * tata otworzył okno) serwer dokłada na jego miejsce w kolejności, gdy jest starsze od ostatnich.
 */
export function getDadNoteRuns(selected: string | null) {
  const query = selected === null ? "" : `?${new URLSearchParams({ selected }).toString()}`

  return call(zGetDadNoteRunsResponse, "getDadNoteRuns", `/api/dad-notes/runs${query}`)
}

/** Dokładnie to, co dostanie Maks z Uwagi taty: tytuł i treść issue składa serwer, przeglądarka je tylko pokazuje. */
export function draftDadNote(text: DadNoteText) {
  return call(zDraftDadNoteResponse, "draftDadNote", "/api/dad-notes/draft", send("POST", text))
}

/** „Wyślij” Uwagi taty; odmawia (`CentrumError`) tylko wtedy, gdy Uwaga nie zapisała się w kolejce. */
export function sendDadNote(note: DadNoteRequest) {
  return call(zSendDadNoteResponse, "sendDadNote", "/api/dad-notes", send("POST", note))
}

/** Serwer kończy pracę po odpowiedzi; odmawia (`CentrumError`), gdy zamknięcie jest teraz zablokowane. */
export function closeCentrum() {
  return call(zCloseCentrumResponse, "closeCentrum", "/api/shutdown", send("POST"))
}

/**
 * Pomiar gotowego widoku do dziennika Centrum, jawny wyjątek od `call` (opisany przy `call`). Porażka
 * wysyłki (także odmowa serwera) przechodzi po cichu: pomiar nigdy nie zmienia UI.
 */
export function recordViewTiming(timing: ViewTiming) {
  fetch("/api/view-timings", { ...send("POST", timing), keepalive: true }).catch(() => undefined)
}
