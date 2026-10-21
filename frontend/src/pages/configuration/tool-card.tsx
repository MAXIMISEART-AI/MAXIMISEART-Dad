import * as React from "react"
import { CircleArrowUpIcon, CircleCheckIcon, CircleDashedIcon, RefreshCwIcon } from "lucide-react"

import { reportToolUpdate, type Configuration, type ToolUpdate } from "@/api/centrum"
import { ReportToMaks } from "@/components/report-to-maks"
import { ThreePartMessage } from "@/components/three-part-message"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { useToolUpdate } from "@/lib/tool-update"

type Freshness = Configuration["freshness"]

type Step = Extract<ToolUpdate, { state: "running" }>["step"]

const FRESHNESS: Record<Freshness, { label: string; icon: React.ReactNode }> = {
  current: { label: "Aktualna", icon: <CircleCheckIcon data-icon="inline-start" className="text-success" /> },
  newer: { label: "Jest nowsza wersja", icon: <CircleArrowUpIcon data-icon="inline-start" className="text-warning" /> },
  not_checked: {
    label: "Nie sprawdzono",
    icon: <CircleDashedIcon data-icon="inline-start" className="text-muted-foreground" />,
  },
}

// Jeden stan w trzech krokach, bez procentów: tata widzi, że trwa, i co teraz.
const STEPS: Record<Step, string> = {
  fetching: "Pobieranie nowej wersji…",
  installing: "Instalowanie bibliotek…",
  restarting: "Ponowne uruchamianie Centrum…",
}

/**
 * Wersja narzędzia z Aktualnością i przyciskiem `Zaktualizuj narzędzie`. Po aktualizacji strona czyta
 * Konfigurację od nowa (`onFinished`), więc commit i Aktualność pochodzą z serwera, nie z wyniku. Po porażce
 * głównym przyciskiem jest to, co każe Komunikat: ponowna aktualizacja albo „Wyślij do Maksa”.
 */
export function ToolCard({
  version,
  commit,
  freshness,
  onFinished,
}: {
  version: string
  commit: string | null
  freshness: Freshness
  onFinished: () => void
}) {
  const { update, busy, start } = useToolUpdate()
  const shownCommit = update?.state === "updated" ? update.commit : commit
  const failedNext = update?.state === "failed" ? update.next_action : null
  const updateIsNext = failedNext === "retry" || (freshness === "newer" && failedNext !== "report")
  const watched = React.useRef(false)

  React.useEffect(() => {
    if (update?.state === "running") {
      watched.current = true
    } else if (watched.current) {
      watched.current = false
      onFinished()
    }
  }, [update, onFinished])

  return (
    <Card role="region" aria-labelledby="narzedzie" className="@4xl/main:col-span-2">
      <CardHeader>
        <CardTitle id="narzedzie">Narzędzie</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
          <span>Wersja {version}</span>
          {shownCommit === null ? null : (
            <>
              <span aria-hidden>·</span>
              <span className="font-mono text-xs" aria-label="Commit">
                {shownCommit}
              </span>
            </>
          )}
          <Badge variant="outline" className="ml-1">
            {FRESHNESS[freshness].icon}
            {FRESHNESS[freshness].label}
          </Badge>
        </CardDescription>
        <CardAction>
          {/* Wyłączony, ale dalej pod kursorem: drugie kliknięcie tylko trafia w przycisk, nie zaznacza tekstu strony. */}
          <Button
            variant={updateIsNext ? "default" : "outline"}
            disabled={busy}
            focusableWhenDisabled
            className="data-disabled:opacity-50"
            onClick={start}
          >
            {busy ? <Spinner data-icon="inline-start" aria-hidden /> : <RefreshCwIcon data-icon="inline-start" />}
            Zaktualizuj narzędzie
          </Button>
        </CardAction>
      </CardHeader>
      {update === null || update.state === "idle" ? null : (
        <CardContent>
          <UpdateStatus update={update} />
        </CardContent>
      )}
    </Card>
  )
}

function UpdateStatus({ update }: { update: Exclude<ToolUpdate, { state: "idle" }> }) {
  if (update.state === "failed") {
    return (
      <div className="flex flex-col gap-3">
        <ThreePartMessage message={update.message} kind="warning" />
        <ReportToMaks
          send={reportToolUpdate}
          report={update.report}
          draft={update.draft}
          primary={update.next_action === "report"}
        />
      </div>
    )
  }

  return (
    <p role="status" className="wejscie flex items-center gap-2 text-sm">
      {update.state === "running" ? (
        <>
          <Spinner aria-hidden className="text-muted-foreground" />
          <span className="text-muted-foreground">{STEPS[update.step]}</span>
        </>
      ) : (
        <>
          <CircleCheckIcon className="size-4 text-success" aria-hidden />
          {update.state === "updated"
            ? "Zaktualizowano. Zamknij Centrum rozliczeń i kliknij skrót."
            : "Masz najnowszą wersję."}
        </>
      )}
    </p>
  )
}
