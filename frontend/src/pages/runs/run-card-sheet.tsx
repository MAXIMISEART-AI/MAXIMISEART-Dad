import * as React from "react"
import { FileClockIcon, RotateCcwIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import { getRunCard, type RunCard, type ProcessRun } from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { HistoryRunCard, ModeBadge } from "@/pages/runs/run-card"

const OPEN = "Karta Uruchomienia"

type Card = { state: "loading" } | { state: "failed"; message: string } | { state: "ready"; card: RunCard }

/** Przycisk wiersza Historii: karta tego Uruchomienia z jego Logów Uruchomienia w panelu z boku. */
export function RunCardButton({ run }: { run: ProcessRun }) {
  const [open, setOpen] = React.useState(false)

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              className="text-muted-foreground"
              aria-label={OPEN}
              onClick={() => setOpen(true)}
            />
          }
        >
          <FileClockIcon />
        </TooltipTrigger>
        <TooltipContent>{OPEN}</TooltipContent>
      </Tooltip>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="gap-0 sm:max-w-3xl data-[side=right]:sm:max-w-3xl">
          <SheetHeader className="pr-12">
            <SheetTitle className="text-lg">{run.process_label}</SheetTitle>
            <SheetDescription className="flex items-center gap-2 tabular-nums">
              Okres {run.period}
              <ModeBadge dryRun={run.mode === "DRY-RUN"} />
            </SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto px-4 pb-6">{open ? <ShownCard runId={run.run_id} /> : null}</div>
        </SheetContent>
      </Sheet>
    </>
  )
}

/** Odczyt karty przy każdym otwarciu panelu (panel montuje treść tylko otwarty). */
function RunCardBody({ runId }: { runId: string }) {
  const [card, setCard] = React.useState<Card>({ state: "loading" })

  const fetchCard = React.useCallback(
    () =>
      getRunCard(runId).then(
        (found) => setCard({ state: "ready", card: found }),
        (failure: Error) => setCard({ state: "failed", message: failureMessage(failure) })
      ),
    [runId]
  )

  React.useEffect(() => {
    fetchCard()
  }, [fetchCard])

  const retry = () => {
    setCard({ state: "loading" })
    fetchCard()
  }

  switch (card.state) {
    case "loading":
      return <Skeleton className="h-64 w-full" aria-label="Wczytywanie karty Uruchomienia" />
    case "failed":
      return (
        <Alert variant="destructive">
          <AlertTitle>Nie udało się odczytać karty Uruchomienia</AlertTitle>
          <AlertDescription>{card.message}</AlertDescription>
          <AlertAction>
            <Button size="sm" variant="outline" onClick={retry}>
              <RotateCcwIcon data-icon="inline-start" />
              Spróbuj ponownie
            </Button>
          </AlertAction>
        </Alert>
      )
    case "ready":
      return card.card.state === "restored" ? <HistoryRunCard card={card.card} /> : <MissingCard />
    default: {
      const unhandled: never = card

      return unhandled
    }
  }
}

/** Wiersz bez identyfikatora Uruchomienia (`.cmd`) karty nie ma, więc panel nie pyta serwera. */
function ShownCard({ runId }: { runId: string | null }) {
  return runId === null ? <MissingCard /> : <RunCardBody runId={runId} />
}

function MissingCard() {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileClockIcon />
        </EmptyMedia>
        <EmptyTitle>Karty tego Uruchomienia nie ma</EmptyTitle>
        <EmptyDescription>Wystartowało spoza Centrum rozliczeń albo jego wynik nie został zachowany.</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
