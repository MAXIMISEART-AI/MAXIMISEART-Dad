import { call } from "@/api/client"
import type {
  GetPeriodBoardResponse,
  OpenRequest,
  Settings,
  ThemeChange,
} from "@/api/generated"
import {
  zChangeThemeResponse,
  zCloseCentrumResponse,
  zChoosePeriodsDirectoryResponse,
  zChooseRegisterResponse,
  zGetPeriodBoardResponse,
  zGetSettingsResponse,
  zOpenPeriodPathResponse,
} from "@/api/generated/zod.gen"

export type {
  Choice,
  NextStep,
  OpenRequest,
  PeriodRow,
  Settings,
} from "@/api/generated"

export type PeriodBoard = GetPeriodBoardResponse

export type PathSetting = Settings["order_register"]

export type Theme = ThemeChange["theme"]

export type OpenTarget = OpenRequest["target"]

function send(method: "POST" | "PUT", body?: OpenRequest | ThemeChange): RequestInit {
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

/** Serwer kończy pracę po odpowiedzi; odmawia (`CentrumError`), gdy zamknięcie jest teraz zablokowane. */
export function closeCentrum() {
  return call(zCloseCentrumResponse, "/api/shutdown", send("POST"))
}
