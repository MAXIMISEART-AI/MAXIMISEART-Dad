import { HistoryIcon, PlayIcon } from "lucide-react"

import { getMetrics, getRunSetup } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { isActive, useRuns } from "@/lib/runs"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { RunHistoryCard } from "@/pages/metrics/run-history-card"
import { RunCard } from "@/pages/runs/run-card"
import { DecisionDialog } from "@/pages/runs/run-dialogs"
import { RunSetupCard } from "@/pages/runs/run-setup-card"

/**
 * Uruchomienia: zakładka „Uruchomienie” z nowym Uruchomieniem procesu albo podglądem na żywo bieżącego
 * (wynik, decyzja taty) i zakładka „Historia” z tą samą tabelą co w Metrykach. Stan Uruchomienia pochodzi
 * wyłącznie ze strumienia serwera, więc przetrwa odświeżenie i ponowne otwarcie karty.
 */
export function RunsPage() {
  const { settings } = useSettings()
  const { view } = useRuns()

  return (
    <Tabs defaultValue="uruchomienie" className="gap-6">
      <PageHeader
        title="Uruchomienia"
        action={
          <TabsList>
            <TabsTrigger value="uruchomienie">
              <PlayIcon data-icon="inline-start" />
              Uruchomienie
            </TabsTrigger>
            <TabsTrigger value="historia">
              <HistoryIcon data-icon="inline-start" />
              Historia
            </TabsTrigger>
          </TabsList>
        }
      />
      <TabsContent value="uruchomienie">
        {/* Zmiana ustawień (np. wskazany Rejestr zleceń) to nowy odczyt tego, czego brakuje do startu. */}
        <RunsContent key={settings.state === "ready" ? JSON.stringify(settings.data) : settings.state} />
      </TabsContent>
      <TabsContent value="historia">
        {/* Każde zakończone Uruchomienie to nowy odczyt historii z plików metryk. */}
        <RunHistory key={view === null || view.state === "idle" || isActive(view) ? "trwa" : view.run.id} />
      </TabsContent>
    </Tabs>
  )
}

function RunHistory() {
  const { resource: metrics } = useResource(getMetrics)

  switch (metrics.state) {
    case "loading":
      return <Skeleton className="h-64 w-full" aria-label="Wczytywanie historii" />
    case "failed":
      return (
        <Alert variant="destructive" className="wejscie">
          <AlertTitle>Nie udało się odczytać historii</AlertTitle>
          <AlertDescription>{metrics.message}</AlertDescription>
        </Alert>
      )
    case "ready":
      return (
        <div className="pojawienie">
          <RunHistoryCard runs={metrics.data.runs} />
        </div>
      )
  }
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
