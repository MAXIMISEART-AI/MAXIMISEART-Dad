import { call } from "@/api/client"
import type {
  DecisionAnswer,
  GetCurrentRunResponse,
  GetPeriodBoardResponse,
  OpenRequest,
  PeriodRow,
  RunEvent,
  RunRequest,
  Settings,
  ThemeChange,
} from "@/api/generated"
import {
  zChangeThemeResponse,
  zCloseCentrumResponse,
  zChoosePeriodsDirectoryResponse,
  zChooseRegisterResponse,
  zDecideRunResponse,
  zDiagnoseRunResponse,
  zGetConfigurationResponse,
  zGetMetricsResponse,
  zGetPeriodBoardResponse,
  zGetRepairNoticeResponse,
  zGetRunSetupResponse,
  zGetSettingsResponse,
  zOpenPeriodPathResponse,
  zReportRunResponse,
  zRunEvent,
  zStartRunResponse,
} from "@/api/generated/zod.gen"

export type {
  Choice,
  Configuration,
  Count,
  Decision,
  DecisionAnswer,
  Diagnosis,
  DiagnosisCheck,
  Figure,
  Message,
  Metrics,
  Percentiles,
  PeriodChoice,
  PeriodRow,
  PeriodFile,
  PhaseProgress,
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
  WorkerFile,
} from "@/api/generated"

export type PeriodBoard = GetPeriodBoardResponse

/** Następny krok okresu: proces z podpowiedzią podglądu albo okres zamknięty (unia z kontraktu). */
export type NextStep = PeriodRow["next_step"]

export type PathSetting = Settings["order_register"]

export type Theme = ThemeChange["theme"]

export type Process = RunRequest["process"]

export type OpenTarget = OpenRequest["target"]

/** Widok bieżącego Uruchomienia procesu; jego `state` to stany UI (unia z kontraktu). */
export type RunView = GetCurrentRunResponse

function send(
  method: "POST" | "PUT",
  body?: OpenRequest | ThemeChange | RunRequest | DecisionAnswer
): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function getSettings() {
  return call(zGetSettingsResponse, "/api/settings")
}

/** Otwiera natywne okno wyboru na komputerze taty i zapamiętuje wybrany Rejestr zleceń. */
export function chooseOrderRegister() {
  return call(zChooseRegisterResponse, "/api/settings/register/choose", send("POST"))
}

/** Otwiera natywne okno wyboru folderu i zapamiętuje folder okresów. */
export function choosePeriodsDirectory() {
  return call(
    zChoosePeriodsDirectoryResponse,
    "/api/settings/periods-directory/choose",
    send("POST")
  )
}

export function changeTheme(theme: Theme) {
  return call(zChangeThemeResponse, "/api/settings/theme", send("PUT", { theme }))
}

export function getPeriodBoard() {
  return call(zGetPeriodBoardResponse, "/api/periods")
}

/** Serwer sam wylicza ścieżkę z folderu okresów; przeglądarka podaje tylko okres i rodzaj pliku. */
export function openPeriodPath(token: string, target: OpenTarget) {
  return call(
    zOpenPeriodPathResponse,
    `/api/periods/${encodeURIComponent(token)}/open`,
    send("POST", { target })
  )
}

/** Co tata wybiera przed Uruchomieniem procesu: procesy, okresy z preselekcją, przypomnienie, brakujące ustawienia. */
export function getRunSetup() {
  return call(zGetRunSetupResponse, "/api/runs/setup")
}

/** Start Uruchomienia procesu; gdy trwa już inne, serwer odmawia z bezpiecznym komunikatem. */
export function startRun(request: RunRequest) {
  return call(zStartRunResponse, "/api/runs", send("POST", request))
}

/** Decyzja taty o niepełnym okresie dla Uruchomienia `runId`. */
export function decideRun(runId: string, answer: DecisionAnswer["answer"]) {
  return call(
    zDecideRunResponse,
    `/api/runs/${encodeURIComponent(runId)}/decision`,
    send("POST", { answer })
  )
}

/** Diagnoza Zatrzymania Uruchomienia `runId`: wyjaśnienie i sprawdzenia; serwer tylko czyta pliki taty. */
export function diagnoseRun(runId: string) {
  return call(zDiagnoseRunResponse, `/api/runs/${encodeURIComponent(runId)}/diagnosis`, send("POST"))
}

/** „Wyślij do Maksa”: serwer wysyła podgląd Zgłoszenia z ostatniej Diagnozy Uruchomienia `runId`. */
export function reportRun(runId: string) {
  return call(zReportRunResponse, `/api/runs/${encodeURIComponent(runId)}/report`, send("POST"))
}

/**
 * Strumień SSE Uruchomień procesu. Najpierw przychodzi bieżący widok, potem każda zmiana; po zerwaniu
 * przeglądarka sama łączy się ponownie i znowu dostaje bieżący widok. Każde zdarzenie jest parsowane
 * schematem z kontraktu; zdarzenie, którego nie da się sparsować, jest pomijane.
 */
export function watchRunEvents(
  onEvent: (event: RunEvent) => void,
  onConnection: (connected: boolean) => void
): () => void {
  const source = new EventSource("/api/runs/events")

  source.addEventListener("open", () => onConnection(true))
  source.addEventListener("error", () => onConnection(false))
  source.addEventListener("message", (message: MessageEvent<string>) => {
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

  return () => source.close()
}

/** Historia Uruchomień procesu z obu plików metryk, z P50/P95 i rozkładem wyników; serwer czyta pliki przy każdym odczycie. */
export function getMetrics() {
  return call(zGetMetricsResponse, "/api/metrics")
}

/** Konfiguracja tylko do odczytu: Wzorce, Wykonawcy i wersja narzędzia. */
export function getConfiguration() {
  return call(zGetConfigurationResponse, "/api/configuration")
}

/** Czy Maks naprawił zgłoszony problem; serwer pyta skrzynkę Zgłoszeń najwyżej raz na 10 minut, bez sieci po cichu. */
export function getRepairNotice() {
  return call(zGetRepairNoticeResponse, "/api/reports/repair")
}

/** Serwer kończy pracę po odpowiedzi; odmawia (`CentrumError`), gdy zamknięcie jest teraz zablokowane. */
export function closeCentrum() {
  return call(zCloseCentrumResponse, "/api/shutdown", send("POST"))
}
