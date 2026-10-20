import * as React from "react"
import {
  ChevronDownIcon,
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
  TriangleAlertIcon,
  WifiOffIcon,
} from "lucide-react"

import type {
  PeriodFile,
  PhaseProgress,
  Progress as RunProgress,
  RunInfo,
  RunOutcome,
  RunSummary,
  RunView,
  WorkerFile,
} from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ThreePartMessage } from "@/components/three-part-message"
import { seconds } from "@/lib/format"
import { useRuns } from "@/lib/runs"
import { openAndConfirm } from "@/pages/periods/open-period-path"
import { CountTiles, NumberStrip } from "@/pages/runs/count-tiles"
import { useStopDiagnosis } from "@/pages/runs/diagnosis"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"

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
                {phase.state === "completed" || phase.state === "failed" ? seconds(phase.duration_ms) : null}
              </span>
            </li>
          ))}
        </ol>
        {view.state === "finished" ? null : <NumberStrip name="Liczniki" figures={view.progress.figures} />}
        {view.state !== "finished" && view.progress.template_total > 0 ? (
          <TemplateProgress progress={view.progress} />
        ) : null}
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
        {view.state === "finished" ? (
          <RunOutcomeSection key={run.id} run={run} result={view.result} reminder={reminder} />
        ) : null}
      </CardContent>
    </Card>
  )
}

function RunOutcomeSection({ run, result, reminder }: { run: RunInfo; result: RunOutcome; reminder: string }) {
  const { start } = useRuns()
  const [confirming, setConfirming] = React.useState(false)
  const openFolder = () => openAndConfirm(run.period, "period_folder", () => undefined)
  const again = (dryRun: boolean) => start({ process: run.process, period: run.period, dry_run: dryRun })
  const diagnosis = useStopDiagnosis(run.id, result.stops[0], () => again(run.dry_run))

  // Rodzaj Zatrzymania wylicza serwer: „do Maksa” i powtórka dostają Diagnozę zamiast następnej akcji.
  const offersDiagnosis = result.stop_kind === "for_maks" || result.stop_kind === "repeated"

  const nextAction = (
    <NextActionButton
      action={result.next_action}
      onRun={() => setConfirming(true)}
      onRerun={() => again(run.dry_run)}
      onOpenFolder={openFolder}
    />
  )

  const action = offersDiagnosis ? diagnosis.action : nextAction

  return (
    <>
      {result.summary === null ? null : <NumberStrip figures={result.summary.figures} />}
      {result.stops.length === 0 ? (
        <Alert className="wejscie p-4" aria-label="Wynik">
          {result.result === "OK" ? (
            <CircleCheckIcon className="text-success!" />
          ) : (
            <TriangleAlertIcon className="text-warning!" />
          )}
          <AlertTitle className="text-base">{result.headline}</AlertTitle>
          <AlertAction className="top-3 right-3">{action}</AlertAction>
        </Alert>
      ) : (
        result.stops.map((stop, index) => (
          <ThreePartMessage key={stop.what} message={stop} kind="stop" action={index === 0 ? action : undefined} />
        ))
      )}
      {offersDiagnosis ? diagnosis.result : null}
      {result.warnings.map((warning) => (
        <ThreePartMessage key={warning.what} message={warning} kind="warning" />
      ))}
      {result.notices.map((notice) => (
        <p key={notice} className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {notice}
        </p>
      ))}
      {result.summary === null ? null : <SummaryDetails summary={result.summary} dryRun={run.dry_run} />}
      <ConfirmRunDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={run.title}
        period={run.period}
        reminder={reminder}
        confirmsReadiness={run.confirms_readiness}
        // „Uruchom” przy wyniku jest tylko po udanym podglądzie bez zapisu tego okresu.
        previewed
        onConfirm={() => again(false)}
      />
    </>
  )
}

/** Jedyna akcja przy wyniku; którą pokazać, mówi serwer. */
function NextActionButton({
  action,
  onRun,
  onRerun,
  onOpenFolder,
}: {
  action: RunOutcome["next_action"]
  onRun: () => void
  onRerun: () => void
  onOpenFolder: () => void
}) {
  switch (action) {
    case "run":
      return (
        <Button size="sm" onClick={onRun}>
          <PlayIcon data-icon="inline-start" />
          Uruchom
        </Button>
      )
    case "rerun":
      return (
        <Button size="sm" variant="outline" onClick={onRerun}>
          <RotateCcwIcon data-icon="inline-start" />
          Uruchom ponownie
        </Button>
      )
    case "open_period_folder":
      return (
        <Button size="sm" variant="outline" onClick={onOpenFolder}>
          <FolderOpenIcon data-icon="inline-start" />
          Folder okresu
        </Button>
      )
    default: {
      const unhandled: never = action

      return unhandled
    }
  }
}

/** Postęp Szablonów pracowników z projekcji: bieżący Wykonawca i „x z y”. */
function TemplateProgress({ progress }: { progress: RunProgress }) {
  const counted = `${progress.templates_completed} z ${progress.template_total}`

  return (
    <Progress
      value={(progress.templates_completed / progress.template_total) * 100}
      getAriaValueText={() => counted}
      aria-label="Szablony pracowników"
    >
      <ProgressLabel>
        Szablony pracowników
        {progress.current_worker === null ? null : (
          <span className="font-normal text-muted-foreground"> · {progress.current_worker}</span>
        )}
      </ProgressLabel>
      <ProgressValue>{() => counted}</ProgressValue>
    </Progress>
  )
}

/** Szczegóły wyniku z serwera: kafelki liczb (np. Zlecenia na dzień), pliki okresu i plan plików. */
function SummaryDetails({ summary, dryRun }: { summary: RunSummary; dryRun: boolean }) {
  return (
    <>
      {summary.counts === null ? null : <CountTiles title={summary.counts.title} counts={summary.counts.counts} />}
      {summary.files.length === 0 ? null : <PeriodFiles files={summary.files} />}
      {summary.file_plan === null ? null : <FilePlan files={summary.file_plan} defaultOpen={dryRun} />}
    </>
  )
}

const PERIOD_FILE_ICONS: Record<PeriodFile["kind"], React.ReactNode> = {
  internal_settlement: <FileTextIcon className="size-4 text-muted-foreground" aria-hidden />,
  collective_file: <FileSpreadsheetIcon className="size-4 text-muted-foreground" aria-hidden />,
}

function PeriodFiles({ files }: { files: ReadonlyArray<PeriodFile> }) {
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm" aria-label="Pliki okresu">
      {files.map((file) => (
        <li key={file.name} className="flex items-center gap-2">
          {PERIOD_FILE_ICONS[file.kind]}
          {file.name}
        </li>
      ))}
    </ul>
  )
}

/** Plan plików: nazwa pliku każdego Wykonawcy i liczba wierszy; po podglądzie rozwinięty od razu. */
function FilePlan({ files, defaultOpen }: { files: ReadonlyArray<WorkerFile>; defaultOpen: boolean }) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="group -ml-2" />}>
        Plan plików ({files.length})
        <ChevronDownIcon
          data-icon="inline-end"
          className="transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="transition-opacity duration-150 ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0">
        <Table aria-label="Plan plików">
          <TableBody>
            {files.map((file) => (
              <TableRow key={file.file}>
                <TableCell>{file.file}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {file.rows === 0 ? <Badge variant="outline">Pusty skoroszyt</Badge> : `${file.rows} ${rowsWord(file.rows)}`}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** „1 wiersz”, „2 wiersze”, „5 wierszy”, „22 wiersze”. */
function rowsWord(count: number): string {
  const lastTwo = count % 100
  const last = count % 10

  if (count === 1) {
    return "wiersz"
  }

  return last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "wiersze" : "wierszy"
}
