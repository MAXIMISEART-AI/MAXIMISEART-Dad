import * as React from "react"
import {
  CircleArrowUpIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  RotateCcwIcon,
  StethoscopeIcon,
} from "lucide-react"

import { failureMessage } from "@/api/client"
import { diagnoseRun, reportRun, type Diagnosis, type DiagnosisCheck, type RunOutcome } from "@/api/centrum"
import { Disclosure } from "@/components/disclosure"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ThreePartMessage } from "@/components/three-part-message"
import { toast } from "@/components/ui/toast"
import { ReportToMaks } from "@/components/report-to-maks"

type StopDiagnosis = {
  /** Akcja przy banerze Zatrzymania: „Diagnoza”, a po niej „Uruchom ponownie”, gdy Diagnoza potwierdza Komunikat. */
  action: React.ReactNode
  /** Wynik Diagnozy i Zgłoszenie do Maksa pod banerem. */
  result: React.ReactNode
}

/**
 * Diagnoza Zatrzymania Uruchomienia `runId`; wynik i rodzaj przyczyny liczy serwer. Przy `offer`
 * `automatic` (nieoczekiwany błąd) zaczyna się sama po pokazaniu wyniku, inaczej na żądanie taty.
 * Gdy wyjaśnienie to ten sam Komunikat co Zatrzymanie (`confirms_stop`), nie powtarza go drugi raz.
 * Nowsza wersja narzędzia obok innej przyczyny (`update_proposal`) to jedno ciche zdanie pod wyjaśnieniem.
 * Pod wynikiem jest Zgłoszenie do Maksa (`report`): przed Diagnozą tylko jego potwierdzenie albo zapisany plik.
 */
export function useStopDiagnosis(
  runId: string,
  offer: RunOutcome["diagnosis"],
  report: RunOutcome["report"],
  onRerun: () => void
): StopDiagnosis {
  const [checking, setChecking] = React.useState(false)
  const [diagnosis, setDiagnosis] = React.useState<Diagnosis | null>(null)
  const started = React.useRef(false)

  const diagnose = React.useCallback(() => {
    started.current = true
    setChecking(true)

    diagnoseRun(runId)
      .then(setDiagnosis, (failure: Error) => {
        toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
      })
      .finally(() => setChecking(false))
  }, [runId])

  React.useEffect(() => {
    if (offer === "automatic" && !started.current) {
      diagnose()
    }
  }, [offer, diagnose])

  if (diagnosis === null) {
    return {
      action: <DiagnoseButton checking={checking} onDiagnose={diagnose} />,
      result:
        report === null ? null : <ReportToMaks send={() => reportRun(runId)} report={report} draft={null} primary={false} />,
    }
  }

  const rerun =
    diagnosis.next_action === "rerun" ? (
      <Button size="sm" onClick={onRerun}>
        <RotateCcwIcon data-icon="inline-start" />
        Uruchom ponownie
      </Button>
    ) : undefined

  return {
    action: diagnosis.confirms_stop ? rerun : undefined,
    result: (
      <section aria-label="Diagnoza" className="wejscie flex flex-col gap-2">
        {diagnosis.confirms_stop ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <StethoscopeIcon className="size-4" aria-hidden />
            Diagnoza potwierdza ten komunikat.
          </p>
        ) : (
          <ThreePartMessage message={diagnosis.explanation} kind="diagnosis" action={rerun} />
        )}
        {diagnosis.update_proposal ? <UpdateProposal /> : null}
        <Checks checks={diagnosis.checks} />
        {report === null ? null : (
          <ReportToMaks
            send={() => reportRun(runId)}
            report={report}
            draft={diagnosis.report}
            primary={diagnosis.next_action === "report"}
          />
        )}
      </section>
    ),
  }
}

/** Propozycja Aktualizacji narzędzia: ciszej niż wyjaśnienie, bo przyczyną Zatrzymania jest co innego. */
function UpdateProposal() {
  return (
    <p role="note" aria-label="Propozycja aktualizacji" className="flex items-center gap-2 text-sm text-muted-foreground">
      <CircleArrowUpIcon className="size-4" aria-hidden />
      Jest też nowsza wersja narzędzia.
    </p>
  )
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
    <Disclosure label={`Sprawdzono (${checks.length})`}>
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
    </Disclosure>
  )
}
