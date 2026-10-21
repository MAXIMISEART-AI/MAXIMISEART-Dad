import * as React from "react"

import { failureMessage } from "@/api/client"
import { getToolUpdate, startToolUpdate, type ToolUpdate } from "@/api/centrum"
import { toast } from "@/components/ui/toast"

// Krok trwającej aktualizacji karta czyta co pół sekundy; poza aktualizacją nie pyta wcale.
const POLL_MS = 500

type ToolUpdateContextValue = {
  /** Aktualizacja narzędzia według serwera; `null`, dopóki żadna strona jej nie odczytała. */
  update: ToolUpdate | null
  /** Start wysłany albo aktualizacja trwa: każdy przycisk aktualizacji jest wtedy wyłączony. */
  busy: boolean
  start: () => void
  read: () => void
}

const ToolUpdateContext = React.createContext<ToolUpdateContextValue | null>(null)

/**
 * Jedna Aktualizacja narzędzia na Centrum, wspólna dla każdego miejsca z przyciskiem `Zaktualizuj narzędzie`.
 * Serwer odpowiada od razu pierwszym krokiem i aktualizuje w tle, a karta odczytuje krok, aż przyjdzie wynik.
 */
export function ToolUpdateProvider({ children }: { children: React.ReactNode }) {
  const [update, setUpdate] = React.useState<ToolUpdate | null>(null)
  const [starting, setStarting] = React.useState(false)
  // Tata klika dwa razy z przyzwyczajenia: drugie kliknięcie przed odpowiedzią serwera nic nie wysyła.
  const sent = React.useRef(false)
  const running = update?.state === "running"

  const read = React.useCallback(() => {
    getToolUpdate().then(setUpdate, () => undefined)
  }, [])

  // Każda odpowiedź w trakcie aktualizacji to nowy obiekt `update`, więc po niej idzie kolejne pytanie.
  React.useEffect(() => {
    if (update?.state !== "running") {
      return
    }

    const timer = window.setTimeout(read, POLL_MS)

    return () => window.clearTimeout(timer)
  }, [update, read])

  const start = React.useCallback(() => {
    if (sent.current) {
      return
    }

    sent.current = true
    setStarting(true)
    startToolUpdate()
      .then(setUpdate, (failure: Error) =>
        toast.add({ title: "Nie zaktualizowano narzędzia", description: failureMessage(failure), type: "error" })
      )
      .finally(() => {
        sent.current = false
        setStarting(false)
      })
  }, [])

  const value = React.useMemo<ToolUpdateContextValue>(
    () => ({ update, busy: starting || running, start, read }),
    [update, starting, running, start, read]
  )

  return <ToolUpdateContext.Provider value={value}>{children}</ToolUpdateContext.Provider>
}

/** Aktualizacja narzędzia dla strony z przyciskiem; strona odczytuje jej stan przy każdym wejściu. */
export function useToolUpdate() {
  const context = React.useContext(ToolUpdateContext)

  if (context === null) {
    throw new Error("useToolUpdate działa tylko wewnątrz ToolUpdateProvider.")
  }

  const { read } = context

  React.useEffect(read, [read])

  return context
}
