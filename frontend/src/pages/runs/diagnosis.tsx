import * as React from "react"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  RotateCcwIcon,
  StethoscopeIcon,
} from "lucide-react"

import { failureMessage } from "@/api/client"
import { diagnoseRun, type Diagnosis, type DiagnosisCheck, type Message, type RunOutcome } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Spinner } from "@/components/ui/spinner"
import { ThreePartMessage } from "@/components/three-part-message"
import { toast } from "@/components/ui/toast"
import { ReportToMaks } from "@/pages/runs/report"

type StopDiagnosis = {
  /** Akcja przy banerze Zatrzymania: „Diagnoza”, a po niej „Uruchom ponownie”, gdy Diagnoza potwierdza Komunikat. */
  action: React.ReactNode
  /** Wynik Diagnozy i Zgłoszenie do Maksa pod banerem. */
  result: React.ReactNode
}

/**
 * Diagnoza Zatrzymania Uruchomienia `runId` na żądanie taty; wynik i rodzaj przyczyny liczy serwer.
 * Gdy wyjaśnienie to ten sam Komunikat co Zatrzymanie, nie powtarza go drugi raz. Pod wynikiem jest
 * Zgłoszenie do Maksa (`report`): przed Diagnozą tylko jego potwierdzenie albo zapisany plik.
 */
export function useStopDiagnosis(
  runId: string,
  stop: Message | undefined,
  report: RunOutcome["report"],
  onRerun: () => void
): StopDiagnosis {
  const [checking, setChecking] = React.useState(false)
  const [diagnosis, setDiagnosis] = React.useState<Diagnosis | null>(null)

  const diagnose = () => {
    setChecking(true)

    diagnoseRun(runId)
      .then(setDiagnosis, (failure: Error) => {
        toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
      })
      .finally(() => setChecking(false))
  }

  if (diagnosis === null) {
    return {
      action: <DiagnoseButton checking={checking} onDiagnose={diagnose} />,
      result:
        report === null ? null : <ReportToMaks runId={runId} report={report} draft={null} primary={false} />,
    }
  }

  const rerun =
    diagnosis.next_action === "rerun" ? (
      <Button size="sm" onClick={onRerun}>
        <RotateCcwIcon data-icon="inline-start" />
        Uruchom ponownie
      </Button>
    ) : undefined

  const confirmsStop = stop !== undefined && sameMessage(stop, diagnosis.explanation)

  return {
    action: confirmsStop ? rerun : undefined,
    result: (
      <section aria-label="Diagnoza" className="wejscie flex flex-col gap-2">
        {confirmsStop ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <StethoscopeIcon className="size-4" aria-hidden />
            Diagnoza potwierdza ten komunikat.
          </p>
        ) : (
          <ThreePartMessage message={diagnosis.explanation} kind="diagnosis" action={rerun} />
        )}
        <Checks checks={diagnosis.checks} />
        {report === null ? null : (
          <ReportToMaks
            runId={runId}
            report={report}
            draft={diagnosis.report}
            primary={diagnosis.next_action === "report"}
          />
        )}
      </section>
    ),
  }
}

function sameMessage(left: Message, right: Message): boolean {
  return left.what === right.what && left.where === right.where && left.action === right.action
}

/** Przycisk „Diagnoza” przy Zatrzymaniu; w trakcie sprawdzania pokazuje, że trwa. */
function DiagnoseButton({ checking, onDiagnose }: { checking: boolean; onDiagnose: () => void }) {
  return (
    <Button size="sm" onClick={onDiagnose} disabled={checking}>
      {checking ? <Spinner data-icon="inline-start" /> : <StethoscopeIcon data-icon="inline-start" />}
      {checking ? "Sprawdzam…" : "Diagnoza"}
    </Button>
  )
}

const CHECK_ICONS: Record<DiagnosisCheck["state"], React.ReactNode> = {
  passed: <CircleCheckIcon className="text-success" aria-label="przeszło" />,
  failed: <CircleXIcon className="text-destructive" aria-label="nie przeszło" />,
  not_checked: <CircleDashedIcon className="text-muted-foreground" aria-label="nie sprawdzono" />,
}

/** Sprawdzenia Diagnozy po kolei, zwinięte: kto chce, zobaczy, co sprawdzono i z jakim wynikiem. */
function Checks({ checks }: { checks: ReadonlyArray<DiagnosisCheck> }) {
  return (
    <Collapsible>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="group -ml-2" />}>
        Sprawdzono ({checks.length})
        <ChevronDownIcon
          data-icon="inline-end"
          className="transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="transition-opacity duration-150 ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0">
        <ul className="flex flex-col gap-2 pt-1 text-sm" aria-label="Sprawdzono">
          {checks.map((check) => (
            <li key={check.label} className="flex gap-2 [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0">
              {CHECK_ICONS[check.state]}
              <span>
                <span className="font-medium">{check.label}</span>
                <span className="text-muted-foreground"> · {check.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
