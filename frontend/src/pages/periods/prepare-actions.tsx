import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import { getRunSetup, type NextStep, type PeriodRow, type Process } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { isActive, useRuns } from "@/lib/runs"
import { useResource } from "@/lib/use-resource"
import type { PageHref } from "@/pages"

const RUNS_PAGE: PageHref = "#/uruchomienia"

/** Proces, który robi następny krok okresu; „none” (okres zamknięty) nie ma procesu. */
const STEP_PROCESSES: Record<Exclude<NextStep["action"], "none">, Process> = {
  prepare_collective_file: "preparation",
  create_worker_settlements: "settlement",
}

/** Proces następnego kroku okresu albo `null`, gdy okres jest zamknięty. */
export function stepProcess(step: NextStep): Process | null {
  return step.action === "none" ? null : STEP_PROCESSES[step.action]
}

function showRuns() {
  window.location.hash = RUNS_PAGE
}

/**
 * Akcja główna karty „Następny krok”: podgląd bez zapisu procesu następnego kroku od razu,
 * a w trakcie Uruchomienia przejście do podglądu na żywo. Podpowiedź podglądu deklaruje proces.
 */
export function PreviewAction({ period, process }: { period: PeriodRow; process: Process }) {
  const { view, start } = useRuns()
  const { resource: setup } = useResource(getRunSetup)

  const hint =
    setup.state === "ready" ? setup.data.processes.find((shown) => shown.process === process)?.preview_hint : undefined

  if (isActive(view)) {
    return (
      <Button size="lg" className="h-11 px-5 text-base" onClick={showRuns}>
        <PlayIcon data-icon="inline-start" />
        Pokaż podgląd na żywo
      </Button>
    )
  }

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            size="lg"
            className="h-11 px-5 text-base"
            onClick={() =>
              start({ process, period: period.token, dry_run: true }).then((started) => started && showRuns())
            }
          />
        }
      >
        <EyeIcon data-icon="inline-start" />
        Podgląd bez zapisu
      </TooltipTrigger>
      {hint === undefined ? null : <TooltipContent>{hint}</TooltipContent>}
    </Tooltip>
  )
}

/** Następny krok w wierszu Tablicy okresów: przejście do Uruchomień z tym procesem i okresem do wybrania. */
export function PrepareLink({ period, process }: { period: PeriodRow; process: Process }) {
  const { setDraft } = useRuns()

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            aria-label={`${period.next_step.label}, okres ${period.token}`}
            onClick={() => {
              setDraft({ process, period: period.token })
              showRuns()
            }}
          />
        }
      >
        {period.next_step.label}
        <ArrowRightIcon data-icon="inline-end" />
      </TooltipTrigger>
      <TooltipContent>{period.next_step.hint}</TooltipContent>
    </Tooltip>
  )
}
