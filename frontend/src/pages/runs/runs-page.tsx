import { getRunSetup } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useRuns } from "@/lib/runs"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { RunCard } from "@/pages/runs/run-card"
import { DecisionDialog } from "@/pages/runs/run-dialogs"
import { RunSetupCard } from "@/pages/runs/run-setup-card"

/**
 * Uruchomienia: nowe Uruchomienie procesu albo podgląd na żywo bieżącego, z wynikiem i decyzją taty.
 * Stan pochodzi wyłącznie ze strumienia serwera, więc przetrwa odświeżenie i ponowne otwarcie karty.
 */
export function RunsPage() {
  const { settings } = useSettings()

  return (
    <>
      <PageHeader title="Uruchomienia" />
      {/* Zmiana ustawień (np. wskazany Rejestr zleceń) to nowy odczyt tego, czego brakuje do startu. */}
      <RunsContent key={settings.state === "ready" ? JSON.stringify(settings.data) : settings.state} />
    </>
  )
}

function RunsContent() {
  const { resource: setup } = useResource(getRunSetup)
  const { view, dismissed, draft, decide, newRun } = useRuns()

  if (view === null || setup.state === "loading") {
    return <RunsSkeleton />
  }

  if (setup.state === "failed") {
    return (
      <Alert variant="destructive" className="wejscie">
        <AlertTitle>Nie udało się odczytać Uruchomień</AlertTitle>
        <AlertDescription>{setup.message}</AlertDescription>
      </Alert>
    )
  }

  const processes = setup.data.processes

  const setupInstead =
    view.state === "idle" || (view.state === "finished" && (view.run.id === dismissed || draft !== null))

  if (setupInstead) {
    return (
      <div className="pojawienie">
        <RunSetupCard processes={processes} />
      </div>
    )
  }

  const reminder = processes.find((process) => process.process === view.run.process)?.reminder ?? ""

  return (
    <div className="pojawienie">
      <RunCard view={view} reminder={reminder} onNewRun={() => newRun(view.run.id)} />
      {view.state === "awaiting_decision" ? (
        <DecisionDialog decision={view.decision} onDecide={(answer) => decide(view.run.id, answer)} />
      ) : null}
    </div>
  )
}

function RunsSkeleton() {
  return (
    <Card aria-busy="true" aria-label="Wczytywanie Uruchomień">
      <CardHeader>
        <Skeleton className="h-6 w-64" />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
        <Skeleton className="h-8 w-full" />
      </CardContent>
    </Card>
  )
}
