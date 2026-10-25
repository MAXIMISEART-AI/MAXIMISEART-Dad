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
  InfoIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  TriangleAlertIcon,
  WifiOffIcon,
} from "lucide-react"

import type {
  Message,
  OpenTarget,
  PeriodFile,
  PhaseProgress,
  Progress as RunProgress,
  RunInfo,
  RunOutcome,
  RunSummary,
  RunView,
  WorkerSettlement,
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
import { StopMessage, ThreePartMessage } from "@/components/three-part-message"
import { WriteAboutRun } from "@/components/write-to-maks"
import { useChangeEntrance } from "@/lib/content-entrance"
import { seconds } from "@/lib/format"
import { useRuns } from "@/lib/runs"
import { openAndConfirm, openOrderRegisterAndConfirm, type OpenedInPeriod } from "@/pages/periods/open-period-path"
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
            <>
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
              <WriteAboutRun runId={run.id} />
            </>
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
  const [confirming, setConfirming] = React.useState(false)
  const open = (target: OpenTarget) => openAndConfirm(run.period, { target })
  const again = (dryRun: boolean) => start({ process: run.process, period: run.period, dry_run: dryRun })
  // Czy i jak proponować Diagnozę, mówi serwer: przy niej przycisk „Diagnoza” zastępuje następną akcję.
  const offersDiagnosis = result.diagnosis !== null
  const diagnosis = useStopDiagnosis(run.id, result.diagnosis, result.report, () => again(run.dry_run))

  const nextAction = (
    <NextActionButton
      action={result.next_action}
      onRun={() => setConfirming(true)}
      onRerun={() => again(run.dry_run)}
      onOpen={open}
    />
  )

  const action = offersDiagnosis ? diagnosis.action : nextAction
  const [stop] = result.stops

  return (
    <>
      {result.summary === null ? null : <NumberStrip figures={result.summary.figures} />}
      {stop === undefined || result.stop_kind === null ? (
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
        <RunStop
          result={result}
          stop={stop}
          kind={result.stop_kind}
          period={run.period}
          action={action}
          openFirst={!offersDiagnosis}
        />
      )}
      {offersDiagnosis ? diagnosis.result : null}
      {result.warnings.map((warning) => (
        <ThreePartMessage key={warning.what} message={warning} kind="warning" />
      ))}
      {result.technical_notes.map((note) => (
        <p key={note} className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {note}
        </p>
      ))}
      {result.summary === null ? null : <SummaryDetails summary={result.summary} run={run} />}
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

type StopKind = NonNullable<RunOutcome["stop_kind"]>

type DadFile = NonNullable<RunOutcome["opens"]>

const FILES_UNCHANGED = "Nic nie zapisano, Twoje pliki są bez zmian."

// Zatrzymanie według Rodzaju Zatrzymania, spójnie z plakietką w Historii: czerwony błąd tylko „do Maksa”.
const STOPS: Record<StopKind, { kind: "stop" | "to_fix" | "declined"; note: string | null }> = {
  for_tata: { kind: "to_fix", note: null },
  repeated: { kind: "to_fix", note: null },
  for_maks: { kind: "stop", note: "To nie wynika z Twoich plików." },
  declined: { kind: "declined", note: null },
}

const DAD_FILES: Record<DadFile, { label: string; open: (period: string) => void }> = {
  order_register: { label: "Otwórz Rejestr zleceń", open: () => openOrderRegisterAndConfirm() },
  collective_file: {
    label: "Otwórz Plik zbiorczy",
    open: (period) => openAndConfirm(period, { target: "collective_file" }),
  },
}

/** Zatrzymanie na karcie wyniku: obok akcji z serwera przycisk pliku taty, w którym jest poprawka. */
function RunStop({
  result,
  stop,
  kind,
  period,
  action,
  openFirst,
}: {
  result: RunOutcome
  stop: Message
  kind: StopKind
  period: string
  action: React.ReactNode
  openFirst: boolean
}) {
  const look = STOPS[kind]
  const notes = [result.files_unchanged ? FILES_UNCHANGED : null, look.note].filter((note) => note !== null)
  const file = result.opens === null ? null : DAD_FILES[result.opens]

  return (
    <StopMessage
      message={stop}
      kind={look.kind}
      title={result.headline}
      notes={notes}
      actions={
        <>
          {file === null ? null : (
            <Button size="sm" variant={openFirst ? "default" : "outline"} onClick={() => file.open(period)}>
              <FileSpreadsheetIcon data-icon="inline-start" />
              {file.label}
            </Button>
          )}
          {action}
        </>
      }
    />
  )
}

/** Jedyna akcja przy wyniku; którą pokazać, mówi serwer. */
function NextActionButton({
  action,
  onRun,
  onRerun,
  onOpen,
}: {
  action: RunOutcome["next_action"]
  onRun: () => void
  onRerun: () => void
  onOpen: (target: OpenTarget) => void
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
    case "open_collective_file":
      return (
        <Button size="sm" onClick={() => onOpen("collective_file")}>
          <FileSpreadsheetIcon data-icon="inline-start" />
          Otwórz Plik zbiorczy
        </Button>
      )
    case "open_worker_settlements_folder":
      return (
        <Button size="sm" onClick={() => onOpen("worker_settlements_folder")}>
          <FolderOpenIcon data-icon="inline-start" />
          Otwórz folder rozliczeń pracowników
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

/** Szczegóły wyniku z serwera: kafelki liczb (np. Zlecenia na dzień), pliki okresu i Rozliczenia pracowników. */
function SummaryDetails({ summary, run }: { summary: RunSummary; run: RunInfo }) {
  // Po podglądzie bez zapisu pliki są tylko planem: jeszcze ich nie ma, więc nie ma czego otwierać.
  const open = run.dry_run ? undefined : (what: OpenedInPeriod) => openAndConfirm(run.period, what)

  return (
    <>
      {summary.counts === null ? null : <CountTiles title={summary.counts.title} counts={summary.counts.counts} />}
      {summary.files.length === 0 ? null : <PeriodFiles files={summary.files} onOpen={open} />}
      {summary.worker_settlements === null ? null : open === undefined ? (
        <FilePlan settlements={summary.worker_settlements} />
      ) : (
        <WorkerSettlements settlements={summary.worker_settlements} onOpen={open} />
      )}
    </>
  )
}

const PERIOD_FILE_ICONS: Record<PeriodFile["kind"], React.ReactNode> = {
  internal_settlement: <FileTextIcon className="size-4 text-muted-foreground" aria-hidden />,
  collective_file: <FileSpreadsheetIcon className="size-4 text-muted-foreground" aria-hidden />,
}

function PeriodFiles({
  files,
  onOpen,
}: {
  files: ReadonlyArray<PeriodFile>
  onOpen: ((what: OpenedInPeriod) => void) | undefined
}) {
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm" aria-label="Pliki okresu">
      {files.map((file) => (
        <li key={file.name} className="flex items-center gap-2">
          {onOpen === undefined ? (
            <>
              {PERIOD_FILE_ICONS[file.kind]}
              {file.name}
            </>
          ) : (
            <Button variant="ghost" size="sm" className="-ml-2 text-sm font-normal" onClick={() => onOpen({ target: file.kind })}>
              {PERIOD_FILE_ICONS[file.kind]}
              {file.name}
            </Button>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Plan plików po podglądzie: każdy Wykonawca, nazwa jego pliku i liczba zleceń; rozwinięty od razu. */
function FilePlan({ settlements }: { settlements: ReadonlyArray<WorkerSettlement> }) {
  return (
    <Disclosure label={`Plan plików (${settlements.length})`} defaultOpen>
      <Table aria-label="Plan plików">
        <TableBody>
          {settlements.map((settlement) => (
            <TableRow key={settlement.file}>
              <TableCell className="font-medium">{settlement.worker}</TableCell>
              <TableCell className="text-muted-foreground">{settlement.file}</TableCell>
              <TableCell className="text-right">
                <OrderCount settlement={settlement} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Disclosure>
  )
}

/** Zapisane Rozliczenia pracowników: Wykonawca, liczba zleceń i otwarcie jego pliku jednym kliknięciem. */
function WorkerSettlements({
  settlements,
  onOpen,
}: {
  settlements: ReadonlyArray<WorkerSettlement>
  onOpen: (what: OpenedInPeriod) => void
}) {
  const title = `Rozliczenia pracowników (${settlements.length})`

  return (
    <section className="flex flex-col gap-2" aria-label="Rozliczenia pracowników">
      <h3 className="text-sm font-medium">{title}</h3>
      <Table aria-label="Rozliczenia pracowników">
        <TableBody>
          {settlements.map((settlement) => (
            <TableRow key={settlement.file}>
              <TableCell className="font-medium">{settlement.worker}</TableCell>
              <TableCell>
                <OrderCount settlement={settlement} />
              </TableCell>
              <TableCell className="text-right">
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Otwórz ${settlement.file}`}
                        onClick={() => onOpen({ worker: settlement.worker })}
                      />
                    }
                  >
                    <FileSpreadsheetIcon data-icon="inline-start" />
                    Otwórz
                  </TooltipTrigger>
                  <TooltipContent>{settlement.file}</TooltipContent>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  )
}

const PLURAL = new Intl.PluralRules("pl-PL")

const ORDER_FORMS: Partial<Record<Intl.LDMLPluralRule, string>> = { one: "zlecenie", few: "zlecenia" }

/** „1 zlecenie”, „2 zlecenia”, „5 zleceń”, „22 zlecenia”; pusty szablon ma oznaczenie, nie tylko zero. */
function OrderCount({ settlement }: { settlement: WorkerSettlement }) {
  if (settlement.empty) {
    return (
      <span className="inline-flex items-center gap-2 text-muted-foreground">
        <Badge variant="outline">pusty</Badge> 0 zleceń w tym tygodniu
      </span>
    )
  }

  return (
    <span className="tabular-nums">
      {settlement.orders} {ORDER_FORMS[PLURAL.select(settlement.orders)] ?? "zleceń"}
    </span>
  )
}
