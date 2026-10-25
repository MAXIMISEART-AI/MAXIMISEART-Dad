import * as React from "react"
import { cn } from "cn"
import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  EyeIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FolderOpenIcon,
  HistoryIcon,
  InfoIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  TriangleAlertIcon,
  WifiOffIcon,
} from "lucide-react"

import type {
  LoggedOutcome,
  NextAction,
  PastRun,
  PeriodFile,
  PhaseProgress,
  Progress as RunProgress,
  RunInfo,
  RunInterrupted,
  RunOutcome,
  RunRestored,
  RunSummary,
  RunView,
  WorkerFile,
} from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Disclosure } from "@/components/disclosure"
import { ThreePartMessage } from "@/components/three-part-message"
import { WriteAboutRun } from "@/components/write-to-maks"
import { useChangeEntrance } from "@/lib/content-entrance"
import { dateTime, seconds } from "@/lib/format"
import { useRuns } from "@/lib/runs"
import { openAndConfirm } from "@/pages/periods/open-period-path"
import { CountTiles, NumberStrip } from "@/pages/runs/count-tiles"
import { useStopDiagnosis } from "@/pages/runs/diagnosis"
import { ConfirmRunDialog } from "@/pages/runs/run-dialogs"

type LiveRun = Exclude<RunView, { state: "idle" }>

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
  view: LiveRun
  reminder: string
  onNewRun: () => void
}) {
  const { disconnected } = useRuns()
  const run = view.run
  const stale = view.state !== "awaiting_decision" && view.progress_stale

  return (
    <Card role="region" aria-label="Podgląd na żywo">
      <RunHeader
        run={run}
        actions={
          view.state === "finished" ? (
            <>
              <NewRunButton onNewRun={onNewRun} />
              <WriteAboutRun runId={run.id} />
            </>
          ) : null
        }
      />
      <CardContent className="flex flex-col gap-6">
        <PhaseList phases={view.progress.phases} />
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

/**
 * Ostatnie Uruchomienie sprzed startu Centrum, z dysku: karta z Logów Uruchomienia albo Uruchomienie, w którego
 * trakcie Centrum się zamknęło. Wygląda jak wynik na żywo, z dopiskiem, skąd jest.
 */
export function PastRunCard({ past, reminder, onNewRun }: { past: PastRun; reminder: string; onNewRun: () => void }) {
  switch (past.state) {
    case "restored":
      return <RestoredRunCard past={past} reminder={reminder} onNewRun={onNewRun} />
    case "interrupted":
      return <InterruptedRunCard past={past} onNewRun={onNewRun} />
    default: {
      const unhandled: never = past

      return unhandled
    }
  }
}

function RestoredRunCard({ past, reminder, onNewRun }: { past: RunRestored; reminder: string; onNewRun: () => void }) {
  const { run, result } = past
  const next = useNextAction(run, result.next_action, reminder)

  return (
    <Card role="region" aria-label="Ostatnie Uruchomienie">
      <RunHeader
        run={run}
        actions={
          <>
            <NewRunButton onNewRun={onNewRun} />
            <WriteAboutRun runId={run.id} />
          </>
        }
      />
      <CardContent className="flex flex-col gap-6">
        <PastNote>Ostatnie Uruchomienie · {dateTime(past.started_at)} · Centrum było od tego czasu zamknięte</PastNote>
        <PhaseList phases={past.phases} />
        <OutcomeBody run={run} result={result} action={next.button} />
        {next.dialog}
      </CardContent>
    </Card>
  )
}

function InterruptedRunCard({ past, onNewRun }: { past: RunInterrupted; onNewRun: () => void }) {
  const { start } = useRuns()
  const run = past.run

  return (
    <Card role="region" aria-label="Ostatnie Uruchomienie">
      <RunHeader run={run} actions={<NewRunButton onNewRun={onNewRun} />} />
      <CardContent className="flex flex-col gap-6">
        <PastNote>Ostatnie Uruchomienie · {dateTime(past.started_at)} · Centrum zamknęło się w trakcie</PastNote>
        <ThreePartMessage
          message={past.advice}
          kind="warning"
          action={<RerunButton onRerun={() => start({ process: run.process, period: run.period, dry_run: run.dry_run })} />}
        />
      </CardContent>
    </Card>
  )
}

/** Karta Uruchomienia z wiersza Historii, tylko do odczytu: etapy i wynik z Logów Uruchomienia, bez akcji. */
export function HistoryRunCard({ card }: { card: RunRestored }) {
  return (
    <div className="flex flex-col gap-6">
      <PastNote>Uruchomienie z {dateTime(card.started_at)}</PastNote>
      <PhaseList phases={card.phases} />
      <OutcomeBody run={card.run} result={card.result} action={null} />
    </div>
  )
}

/** Okres, proces, tryb i akcje karty Uruchomienia. */
function RunHeader({ run, actions }: { run: RunInfo; actions: React.ReactNode }) {
  return (
    <CardHeader>
      <CardDescription className="tabular-nums">Okres {run.period}</CardDescription>
      <CardTitle className="text-lg">{run.title}</CardTitle>
      <CardAction className="flex items-center gap-2">
        <ModeBadge dryRun={run.dry_run} />
        {actions}
      </CardAction>
    </CardHeader>
  )
}

export function ModeBadge({ dryRun }: { dryRun: boolean }) {
  return (
    <Badge variant={dryRun ? "outline" : "default"}>
      {dryRun ? <EyeIcon data-icon="inline-start" /> : null}
      {dryRun ? "Bez zapisu" : "Z zapisem"}
    </Badge>
  )
}

function PastNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4" aria-hidden />
      {children}
    </p>
  )
}

function NewRunButton({ onNewRun }: { onNewRun: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<Button variant="ghost" size="icon-sm" aria-label="Nowe Uruchomienie procesu" onClick={onNewRun} />}
      >
        <PlusIcon />
      </TooltipTrigger>
      <TooltipContent>Nowe Uruchomienie procesu</TooltipContent>
    </Tooltip>
  )
}

function PhaseList({ phases }: { phases: ReadonlyArray<PhaseProgress> }) {
  return (
    <ol className="grid grid-cols-4 gap-4" aria-label="Etapy">
      {phases.map((phase) => (
        <li
          key={phase.phase}
          className="flex flex-col gap-2"
          aria-label={`${phase.phase}: ${PHASE_STATE_LABELS[phase.state]}`}
        >
          <span className="flex items-center gap-2 text-sm font-medium [&_svg]:size-4">
            <PhaseIcon state={phase.state} />
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
  )
}

/** Ikona stanu etapu. Ikona stanu, który zmienił się na oczach taty, wchodzi `podmiana`; zastana stoi. */
function PhaseIcon({ state }: { state: PhaseProgress["state"] }) {
  const entrance = useChangeEntrance(state, "podmiana")

  return (
    <span key={state} className={cn("flex", entrance)}>
      {PHASE_ICONS[state]}
    </span>
  )
}

function RunOutcomeSection({ run, result, reminder }: { run: RunInfo; result: RunOutcome; reminder: string }) {
  const { start } = useRuns()
  const next = useNextAction(run, result.next_action, reminder)
  // Czy i jak proponować Diagnozę, mówi serwer: przy niej przycisk „Diagnoza” zastępuje następną akcję.
  const offersDiagnosis = result.diagnosis !== null

  const diagnosis = useStopDiagnosis(run.id, result.diagnosis, result.report, () =>
    start({ process: run.process, period: run.period, dry_run: run.dry_run })
  )

  return (
    <>
      <OutcomeBody
        run={run}
        result={result}
        action={offersDiagnosis ? diagnosis.action : next.button}
        below={offersDiagnosis ? diagnosis.result : null}
      />
      {next.dialog}
    </>
  )
}

/** Wynik: liczby, tytuł albo Zatrzymania z akcją, ostrzeżenia, uwagi techniczne i szczegóły podsumowania. */
function OutcomeBody({
  run,
  result,
  action,
  below = null,
}: {
  run: RunInfo
  result: LoggedOutcome
  action: React.ReactNode
  below?: React.ReactNode
}) {
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
          {action === null ? null : <AlertAction className="top-3 right-3">{action}</AlertAction>}
        </Alert>
      ) : (
        result.stops.map((stop, index) => (
          <ThreePartMessage
            key={stop.what}
            message={stop}
            kind="stop"
            action={index === 0 && action !== null ? action : undefined}
          />
        ))
      )}
      {below}
      {result.warnings.map((warning) => (
        <ThreePartMessage key={warning.what} message={warning} kind="warning" />
      ))}
      {result.technical_notes.map((note) => (
        <p key={note} className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {note}
        </p>
      ))}
      {result.summary === null ? null : <SummaryDetails summary={result.summary} dryRun={run.dry_run} />}
    </>
  )
}

/** Akcja po wyniku, którą proponuje serwer, z potwierdzeniem zapisu przy „Uruchom”. */
function useNextAction(run: RunInfo, action: NextAction, reminder: string) {
  const { start } = useRuns()
  const [confirming, setConfirming] = React.useState(false)
  const again = (dryRun: boolean) => start({ process: run.process, period: run.period, dry_run: dryRun })

  return {
    button: (
      <NextActionButton
        action={action}
        onRun={() => setConfirming(true)}
        onRerun={() => again(run.dry_run)}
        onOpenFolder={() => openAndConfirm(run.period, "period_folder", () => undefined)}
      />
    ),
    dialog: (
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
    ),
  }
}

/** Jedyna akcja przy wyniku; którą pokazać, mówi serwer. */
function NextActionButton({
  action,
  onRun,
  onRerun,
  onOpenFolder,
}: {
  action: NextAction
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
      return <RerunButton onRerun={onRerun} />
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

function RerunButton({ onRerun }: { onRerun: () => void }) {
  return (
    <Button size="sm" variant="outline" onClick={onRerun}>
      <RotateCcwIcon data-icon="inline-start" />
      Uruchom ponownie
    </Button>
  )
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
    <Disclosure label={`Plan plików (${files.length})`} defaultOpen={defaultOpen}>
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
    </Disclosure>
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
