import * as React from "react"

import { failureMessage } from "@/api/client"

/** Stan odczytu z serwera. Ponowny odczyt zostawia poprzednie dane, więc widok nie miga szkieletem. */
export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "failed"; message: string }

/**
 * Odczyt z serwera z ponowieniem na żądanie i po powrocie do karty: Status okresu wylicza serwer
 * z plików przy każdym odczycie, więc po zmianach w Eksploratorze wystarczy wrócić do karty.
 * Liczy się tylko najnowszy odczyt. `load` musi być stabilne (funkcja z `@/api/centrum`).
 */
export function useResource<T>(load: () => Promise<T>) {
  const [resource, setResource] = React.useState<Resource<T>>({ state: "loading" })
  const latest = React.useRef(0)

  const reload = React.useCallback(() => {
    const request = ++latest.current

    load().then(
      (data) => request === latest.current && setResource({ state: "ready", data }),
      (failure: Error) =>
        request === latest.current &&
        setResource({ state: "failed", message: failureMessage(failure) })
    )
  }, [load])

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

  // Wynik akcji (np. wybór w oknie) zastępuje odczyt, który był jeszcze w drodze.
  const replace = React.useCallback((next: Resource<T>) => {
    latest.current++
    setResource(next)
  }, [])

  return { resource, reload, replace }
}
