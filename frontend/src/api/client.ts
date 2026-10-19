import type * as z from "zod"

import { zProblem } from "@/api/generated/zod.gen"

/** Odmowa albo awaria z komunikatem, który można pokazać tacie (bez treści błędu technicznego). */
export class CentrumError extends Error {}

const UNREACHABLE =
  "Centrum rozliczeń nie odpowiada. Zamknij kartę i uruchom Centrum ponownie."

const UNEXPECTED =
  "Centrum rozliczeń odpowiedziało w nieoczekiwany sposób. Odśwież kartę."

export function failureMessage(failure: Error): string {
  return failure instanceof CentrumError ? failure.message : UNEXPECTED
}

/**
 * Jedyna droga do serwera: każda odpowiedź jest parsowana schematem wygenerowanym z kontraktu,
 * zanim trafi do UI. Odmowa serwera (`Problem`) staje się `CentrumError` z jego komunikatem.
 */
export async function call<T>(
  schema: z.ZodType<T>,
  path: string,
  init?: RequestInit
): Promise<T> {
  let response: Response

  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    })
  } catch {
    throw new CentrumError(UNREACHABLE)
  }

  const body: unknown = await response.json().catch(() => null)

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
