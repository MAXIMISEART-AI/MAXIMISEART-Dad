import * as React from "react"
import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  EyeIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FolderOpenIcon,
  InfoIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  WifiOffIcon,
} from "lucide-react"

import type { PhaseProgress, PreparationSummary, RunInfo, RunResult, RunView } from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { previewKey, useRuns } from "@/lib/runs"
import { openAndConfirm } from "@/pages/periods/open-period-path"
import { CountTiles, NumberStrip } from "@/pages/runs/count-tiles"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"
import { ThreePartMessage } from "@/pages/runs/three-part-message"

type ShownRun = Exclude<RunView, { state: "idle" }>

const PHASE_ICONS: Record<PhaseProgress["state"], React.ReactNode> = {
  pending: <CircleDashedIcon className="text-muted-foreground" aria-hidden />,
  running: <Spinner />,
  completed: <CircleCheckIcon className="text-success" aria-hidden />,
  failed: <CircleXIcon className="text-destructive" aria-hidden />,
}

const PHASE_STATE_LABELS: Record<PhaseProgress["state"], string> = {
  pending: "oczekuje",
  running: "trwa",
  completed: "zakończony",
  failed: "przerwany",
}

// Etap, który trwa, ma pasek nieokreślony (`null`): czasu etapu nie znamy z góry.
const PHASE_VALUES: Record<PhaseProgress["state"], number | null> = {
  pending: 0,
  running: null,
  completed: 100,
  failed: 100,
}

function duration(milliseconds: number): string {
  return milliseconds < 1000
    ? `${milliseconds} ms`
    : `${(milliseconds / 1000).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} s`
}

/** Podgląd na żywo bieżącego Uruchomienia procesu i jego wynik; wszystko z widoku serwera. */
export function RunCard({
  view,
  reminder,
  onNewRun,
}: {
  view: ShownRun
  reminder: string
  onNewRun: () => void
}) {
  const { disconnected } = useRuns()
  const run = view.run
  const stale = view.state !== "awaiting_decision" && view.progress_stale

  return (
    <Card role="region" aria-label="Podgląd na żywo">
      <CardHeader>
        <CardDescription className="tabular-nums">Okres {run.period}</CardDescription>
        <CardTitle className="text-lg">{run.title}</CardTitle>
        <CardAction className="flex items-center gap-2">
          <Badge variant={run.dry_run ? "outline" : "default"}>
            {run.dry_run ? <EyeIcon data-icon="inline-start" /> : null}
            {run.dry_run ? "Bez zapisu" : "Z zapisem"}
          </Badge>
          {view.state === "finished" ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Nowe Uruchomienie procesu"
                    onClick={onNewRun}
                  />
                }
              >
                <PlusIcon />
              </TooltipTrigger>
              <TooltipContent>Nowe Uruchomienie procesu</TooltipContent>
            </Tooltip>
          ) : null}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <ol className="grid grid-cols-4 gap-4" aria-label="Etapy">
          {view.progress.phases.map((phase) => (
            <li
              key={phase.phase}
              className="flex flex-col gap-2"
              aria-label={`${phase.phase}: ${PHASE_STATE_LABELS[phase.state]}`}
            >
              <span className="flex items-center gap-2 text-sm font-medium [&_svg]:size-4">
                {PHASE_ICONS[phase.state]}
                <span data-pending={phase.state === "pending"} className="data-[pending=true]:text-muted-foreground">
                  {phase.phase}
                </span>
              </span>
              <Progress
                value={PHASE_VALUES[phase.state]}
                aria-label={phase.phase}
                className={phase.state === "failed" ? "**:data-[slot=progress-indicator]:bg-destructive" : undefined}
              />
              <span className="h-4 text-xs text-muted-foreground tabular-nums">
                {phase.state === "completed" || phase.state === "failed" ? duration(phase.duration_ms) : null}
              </span>
            </li>
          ))}
        </ol>
        {stale && view.state === "running" ? (
          <Alert className="wejscie">
            <WifiOffIcon />
            <AlertTitle>Podgląd przestał się aktualizować</AlertTitle>
            <AlertDescription>Uruchomienie trwa dalej. Wynik pojawi się tutaj.</AlertDescription>
          </Alert>
        ) : null}
        {disconnected && view.state !== "finished" ? (
          <Alert className="wejscie">
            <WifiOffIcon />
            <AlertTitle>Brak połączenia z Centrum rozliczeń</AlertTitle>
            <AlertDescription>Łączę ponownie. Uruchomienie trwa dalej na komputerze.</AlertDescription>
          </Alert>
        ) : null}
        {view.state === "awaiting_decision" ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <InfoIcon className="size-4" aria-hidden />
            Czeka na Twoją decyzję.
          </p>
        ) : null}
        {view.state === "finished" ? <RunOutcome run={run} result={view.result} reminder={reminder} /> : null}
      </CardContent>
    </Card>
  )
}

function RunOutcome({ run, result, reminder }: { run: RunInfo; result: RunResult; reminder: string }) {
  const { start, previewed } = useRuns()
  const [confirming, setConfirming] = React.useState(false)
  const openFolder = () => openAndConfirm(run.period, "period_folder", () => undefined)
  const again = (dryRun: boolean) => start({ process: run.process, period: run.period, dry_run: dryRun })

  const action =
    result.next_action === "run" ? (
      <Button size="sm" onClick={() => setConfirming(true)}>
        <PlayIcon data-icon="inline-start" />
        Uruchom
      </Button>
    ) : result.next_action === "rerun" ? (
      <Button size="sm" variant="outline" onClick={() => again(run.dry_run)}>
        <RotateCcwIcon data-icon="inline-start" />
        Uruchom ponownie
      </Button>
    ) : (
      <Button size="sm" variant="outline" onClick={openFolder}>
        <FolderOpenIcon data-icon="inline-start" />
        Folder okresu
      </Button>
    )

  return (
    <>
      {result.summary === null ? null : <SummaryNumbers summary={result.summary} />}
      {result.stops.length === 0 ? (
        <Alert className="wejscie p-4" aria-label="Wynik">
          <CircleCheckIcon className="text-success!" />
          <AlertTitle className="text-base">{result.headline}</AlertTitle>
          <AlertAction className="top-3 right-3">{action}</AlertAction>
        </Alert>
      ) : (
        result.stops.map((stop, index) => (
          <ThreePartMessage key={stop.what} message={stop} kind="stop" action={index === 0 ? action : undefined} />
        ))
      )}
      {result.warnings.map((warning) => (
        <ThreePartMessage key={warning.what} message={warning} kind="warning" />
      ))}
      {result.notices.map((notice) => (
        <p key={notice} className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {notice}
        </p>
      ))}
      {result.summary === null ? null : <SummaryDetails summary={result.summary} />}
      <ConfirmRunDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={run.title}
        period={run.period}
        reminder={reminder}
        previewed={previewed.has(previewKey(run))}
        onConfirm={() => again(false)}
      />
    </>
  )
}

function SummaryNumbers({ summary }: { summary: PreparationSummary }) {
  return (
    <NumberStrip
      numbers={[
        ["Zlecenia okresu", summary.period_order_count],
        ["Zlecenia skuteczne", summary.successful_order_count],
        ["Pominięte puste wiersze", summary.skipped_empty_rows],
      ]}
    />
  )
}

function SummaryDetails({ summary }: { summary: PreparationSummary }) {
  return (
    <>
      <CountTiles title="Zlecenia na dzień" counts={summary.orders_per_day} />
      <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm" aria-label="Pliki okresu">
        <li className="flex items-center gap-2">
          <FileTextIcon className="size-4 text-muted-foreground" aria-hidden />
          {summary.internal_settlement_file}
        </li>
        <li className="flex items-center gap-2">
          <FileSpreadsheetIcon className="size-4 text-muted-foreground" aria-hidden />
          {summary.collective_file}
        </li>
      </ul>
    </>
  )
}
