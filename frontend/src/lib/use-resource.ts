import * as React from "react"

import { failureMessage } from "@/api/client"

/** Stan odczytu z serwera. Ponowny odczyt zostawia poprzednie dane, więc widok nie miga szkieletem. */
export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "failed"; message: string }

type Load<T> = () => Promise<T>

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
 * Liczy się tylko najnowszy odczyt. `load` musi być stabilne (funkcja z `@/api/centrum`).
 */
export function useResource<T>(load: Load<T>) {
  const [resource, setResource] = React.useState<Resource<T>>(() => lastData(load))
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
    load().then(
      (data) => request === latest.current && show(request, { state: "ready", data }),
      (failure: Error) =>
        request === latest.current && show(request, { state: "failed", message: failureMessage(failure) })
    )
  }, [load, show])

  React.useEffect(() => {
    const reloadWhenVisible = () => {
      if (document.visibilityState === "visible") {
        reload()
      }
    }

    reload()
    window.addEventListener("focus", reload)
    document.addEventListener("visibilitychange", reloadWhenVisible)

    return () => {
      window.removeEventListener("focus", reload)
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
