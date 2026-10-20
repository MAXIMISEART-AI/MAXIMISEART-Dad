import type * as z from "zod"

import type { ApiTiming } from "@/api/generated"
import { zProblem } from "@/api/generated/zod.gen"

/** Odmowa albo awaria z komunikatem, który można pokazać tacie (bez treści błędu technicznego). */
class CentrumError extends Error {}

const UNREACHABLE =
  "Centrum rozliczeń nie odpowiada. Zamknij kartę i uruchom Centrum ponownie."

const UNEXPECTED =
  "Centrum rozliczeń odpowiedziało w nieoczekiwany sposób. Odśwież kartę."

export function failureMessage(failure: Error): string {
  return failure instanceof CentrumError ? failure.message : UNEXPECTED
}

type Operation = ApiTiming["operation"]

/** Zakończone zapytanie API z czasami do pomiaru widoku (`performance.now()` w milisekundach). */
type TimedRequest = ApiTiming & { started: number; ended: number }

// Zapytania od początku bieżącego widoku; pomiar widoku bierze te, które skończyły się przed gotową treścią.
let timedRequests: TimedRequest[] = []

// Odświeżanie po powrocie do karty dopisuje zapytania bez nowego widoku, więc pamięć ma górną granicę.
const REMEMBERED_REQUESTS = 50

/** Zapytania zakończone w `[from, to]` i zapomina wcześniejsze niż `from` (początek nowego widoku). */
export function requestsBetween(from: number, to: number): TimedRequest[] {
  timedRequests = timedRequests.filter((request) => request.started >= from)

  return timedRequests.filter((request) => request.ended <= to)
}

/** Czas serwera z nagłówka `Server-Timing` (`centrum;dur=12.3`); `null`, gdy go brak. */
function serverMs(response: Response): number | null {
  const duration = /dur=(\d+(?:\.\d+)?)/.exec(response.headers.get("Server-Timing") ?? "")

  return duration === null ? null : Math.round(Number(duration[1]))
}

/**
 * Jedyna droga do serwera: każda odpowiedź jest parsowana schematem wygenerowanym z kontraktu,
 * zanim trafi do UI. Odmowa serwera (`Problem`) staje się `CentrumError` z jego komunikatem.
 * Czas każdego zapytania trafia do pomiaru widoku pod nazwą `operation` z kontraktu, nie pod adresem.
 */
export async function call<T>(
  schema: z.ZodType<T>,
  operation: Operation,
  path: string,
  init?: RequestInit
): Promise<T> {
  let response: Response
  // `Headers` przyjmuje każdą postać nagłówków z `RequestInit`; rozpakowanie `...` gubi obiekt `Headers`.
  const headers = new Headers(init?.headers)
  const started = performance.now()

  headers.set("Accept", "application/json")

  try {
    response = await fetch(path, { ...init, headers })
  } catch {
    throw new CentrumError(UNREACHABLE)
  }

  const body: unknown = await response.json().catch(() => null)
  const ended = performance.now()

  if (timedRequests.length >= REMEMBERED_REQUESTS) {
    timedRequests.shift()
  }

  timedRequests.push({
    operation,
    browser_ms: Math.round(ended - started),
    server_ms: serverMs(response),
    started,
    ended,
  })

  if (!response.ok) {
    const problem = zProblem.safeParse(body)

    throw new CentrumError(problem.success ? problem.data.message : UNEXPECTED)
  }

  const parsed = schema.safeParse(body)

  if (!parsed.success) {
    throw new CentrumError(UNEXPECTED)
  }

  return parsed.data
}
