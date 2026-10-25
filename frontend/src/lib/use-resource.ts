import * as React from "react"

import { failureMessage } from "@/api/client"

/** Stan odczytu z serwera. Ponowny odczyt zostawia poprzednie dane, więc widok nie miga szkieletem. */
export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "failed"; message: string }

type Load<T> = () => Promise<T>

type ReturnSignal = "focus" | "visible"

type LastRead = { data: unknown; read: number }

// Ostatnie dane każdego odczytu, pod funkcją odczytu z `@/api/centrum`. To tylko kopia ostatniej odpowiedzi
// serwera w pamięci karty (odświeżenie karty ją czyści); źródłem Statusu okresu nadal jest serwer (ADR 0004).
const lastReads = new Map<Load<unknown>, LastRead>()

// Numer każdego odczytu i każdej podmiany: kopię nadpisuje tylko nowszy, także z innej strony.
let reads = 0

function lastData<T>(load: Load<T>): Resource<T> {
  const last = lastReads.get(load)

  if (last === undefined) {
    return { state: "loading" }
  }

  // SAFETY: wpis pod kluczem `load` zapisuje tylko `remember` z danymi, które zwróciło to samo `load`.
  return { state: "ready", data: last.data as T }
}

function remember<T>(load: Load<T>, read: number, next: Resource<T>) {
  const last = lastReads.get(load)

  if (last !== undefined && last.read > read) {
    return
  }

  // Nieudany odczyt usuwa kopię: przy następnym wejściu tata zobaczy szkielet, a nie dane sprzed porażki.
  if (next.state === "ready") {
    lastReads.set(load, { data: next.data, read })
  } else {
    lastReads.delete(load)
  }
}

/** Zapomina ostatnie dane wszystkich odczytów: po zmianie folderu okresów albo Rejestru zleceń są z innych plików. */
export function forgetLastReads() {
  lastReads.clear()
}

/**
 * Odczyt z serwera z ponowieniem na żądanie i po powrocie do karty: Status okresu wylicza serwer
 * z plików przy każdym odczycie, więc po zmianach w Eksploratorze wystarczy wrócić do karty.
 * Strona, na której tata już był, od razu pokazuje ostatnie dane i czyta od nowa w tle.
 * Z `fresh` pierwszy widok czeka na odczyt zamiast pokazać ostatnie dane, bo mogą być sprzed zmiany plików.
 * Liczy się tylko najnowszy odczyt. `load` musi być stabilne (funkcja z `@/api/centrum`).
 */
export function useResource<T>(load: Load<T>, { fresh = false }: { fresh?: boolean } = {}) {
  const [resource, setResource] = React.useState<Resource<T>>(() => (fresh ? { state: "loading" } : lastData(load)))
  const latest = React.useRef(0)

  const show = React.useCallback(
    (read: number, next: Resource<T>) => {
      remember(load, read, next)
      setResource(next)
    },
    [load]
  )

  const reload = React.useCallback(() => {
    const request = ++reads

    latest.current = request

    return load().then(
      (data) => {
        if (request === latest.current) {
          show(request, { state: "ready", data })
        }
      },
      (failure: Error) => {
        if (request === latest.current) {
          show(request, { state: "failed", message: failureMessage(failure) })
        }
      }
    )
  }, [load, show])

  React.useEffect(() => {
    // Powrót do karty daje `visibilitychange` i `focus`, w dowolnej kolejności. Gdy odczyt po jednym z nich
    // jest jeszcze w drodze, drugi należy do tego samego powrotu i nie czyta drugi raz.
    let returning: { signal: ReturnSignal; read: Promise<unknown> } | undefined

    const readOnReturn = (signal: ReturnSignal) => {
      if (returning !== undefined && returning.signal !== signal) {
        return
      }

      const current = { signal, read: reload() }

      returning = current
      current.read.finally(() => {
        if (returning === current) {
          returning = undefined
        }
      })
    }

    const reloadOnFocus = () => readOnReturn("focus")

    const reloadWhenVisible = () => {
      if (document.visibilityState === "visible") {
        readOnReturn("visible")
      } else {
        returning = undefined
      }
    }

    reload()
    window.addEventListener("focus", reloadOnFocus)
    document.addEventListener("visibilitychange", reloadWhenVisible)

    return () => {
      window.removeEventListener("focus", reloadOnFocus)
      document.removeEventListener("visibilitychange", reloadWhenVisible)
    }
  }, [reload])

  // Wynik akcji (np. wybór w oknie) zastępuje odczyt, który był jeszcze w drodze, także w kopii.
  const replace = React.useCallback(
    (next: Resource<T>) => {
      const request = ++reads

      latest.current = request
      show(request, next)
    },
    [show]
  )

  return { resource, reload, replace }
}
