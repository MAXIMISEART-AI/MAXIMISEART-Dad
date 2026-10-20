import * as React from "react"

import { failureMessage } from "@/api/client"
import {
  decideRun,
  startRun,
  watchRunEvents,
  type DecisionAnswer,
  type RunEvent,
  type RunRequest,
  type RunView,
} from "@/api/centrum"
import { toast } from "@/components/ui/toast"

/** Okres i proces wybrane w innym miejscu (np. w Tablicy okresów) do formularza nowego Uruchomienia. */
export type RunDraft = Pick<RunRequest, "process" | "period">

type RunsContextValue = {
  /** Bieżące Uruchomienie procesu ze strumienia; `null`, dopóki nie przyjdzie pierwszy widok. */
  view: RunView | null
  /** Połączenie ze strumieniem zerwane; przeglądarka łączy się ponownie sama. */
  disconnected: boolean
  draft: RunDraft | null
  setDraft: (draft: RunDraft | null) => void
  /** Zakończone Uruchomienie, którego wynik tata odłożył przyciskiem „Nowe Uruchomienie procesu”. */
  dismissed: string | null
  newRun: (finishedRunId: string) => void
  start: (request: RunRequest) => Promise<boolean>
  decide: (runId: string, answer: DecisionAnswer["answer"]) => Promise<void>
}

const RunsContext = React.createContext<RunsContextValue | null>(null)

function showFailure(failure: Error) {
  toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
}

/** Powiadomienie tylko po zakończonym zapisie (RUN), widzianym na żywo; podgląd i zatrzymanie mają baner. */
function announce(event: RunEvent, before: RunView | null) {
  const view = event.view

  if (view.state !== "finished" || view.run.dry_run || view.result.ending !== "finished") {
    return
  }

  if (before === null || before.state === "idle") {
    return
  }

  if (before.run.id !== view.run.id || before.state === "finished") {
    return
  }

  toast.add({
    title: view.result.headline,
    description: `Okres ${view.run.period}`,
    type: view.result.result === "OK" ? "success" : "warning",
  })
}

/**
 * Jeden strumień Uruchomień na kartę, póki jest widoczna: każda strona widzi to samo bieżące Uruchomienie
 * procesu, a zamknięcie karty albo przejście do innej nie przerywa pracy na serwerze.
 */
export function RunsProvider({ children }: { children: React.ReactNode }) {
  const [view, setView] = React.useState<RunView | null>(null)
  const [disconnected, setDisconnected] = React.useState(false)
  const [draft, setDraft] = React.useState<RunDraft | null>(null)
  const [dismissed, setDismissed] = React.useState<string | null>(null)
  const latest = React.useRef<RunView | null>(null)

  React.useEffect(
    () =>
      watchRunEvents(
        (event) => {
          announce(event, latest.current)
          latest.current = event.view
          setView(event.view)
        },
        (connected) => setDisconnected(!connected)
      ),
    []
  )

  const value = React.useMemo<RunsContextValue>(
    () => ({
      view,
      disconnected,
      draft,
      setDraft,
      dismissed,
      newRun: setDismissed,
      start: (request) =>
        startRun(request).then(
          () => {
            setDraft(null)

            return true
          },
          (failure: Error) => {
            showFailure(failure)

            return false
          }
        ),
      decide: (runId, answer) => decideRun(runId, answer).then(() => undefined, showFailure),
    }),
    [view, disconnected, draft, dismissed]
  )

  return <RunsContext.Provider value={value}>{children}</RunsContext.Provider>
}

export function useRuns() {
  const context = React.useContext(RunsContext)

  if (context === null) {
    throw new Error("useRuns działa tylko wewnątrz RunsProvider.")
  }

  return context
}

/** Uruchomienie trwa (także gdy czeka na decyzję taty). */
export function isActive(view: RunView | null): boolean {
  return view !== null && (view.state === "running" || view.state === "awaiting_decision")
}
