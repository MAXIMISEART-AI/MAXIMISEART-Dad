import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import type { NextStep, PeriodRow, Process, ProcessStep } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { isActive, useRuns } from "@/lib/runs"
import type { PageHref } from "@/pages"

const RUNS_PAGE: PageHref = "#/uruchomienia"

/** Proces, który robi następny krok okresu; „none” (okres zamknięty) nie ma procesu. */
const STEP_PROCESSES: Record<ProcessStep["action"], Process> = {
  prepare_collective_file: "preparation",
  create_worker_settlements: "settlement",
}

/** Proces następnego kroku okresu albo `null`, gdy okres jest zamknięty. */
export function stepProcess(step: NextStep): Process | null {
  return step.action === "none" ? null : STEP_PROCESSES[step.action]
}

const PRIMARY_LOOK = { size: "lg", className: "h-11 px-5 text-base" } as const

const SECONDARY_LOOK = { variant: "ghost", className: "text-muted-foreground" } as const

function showRuns() {
  window.location.hash = RUNS_PAGE
}

/**
 * Akcja karty „Następny krok”: podgląd bez zapisu procesu następnego kroku od razu,
 * a w trakcie Uruchomienia przejście do podglądu na żywo. Podpowiedź podglądu przychodzi z krokiem.
 * Główna, chyba że karta ma inną akcję główną (`secondary`).
 */
export function PreviewAction({
  period,
  step,
  secondary,
}: {
  period: PeriodRow
  step: ProcessStep
  secondary: boolean
}) {
  const { view, start } = useRuns()
  const process = STEP_PROCESSES[step.action]
  const look = secondary ? SECONDARY_LOOK : PRIMARY_LOOK

  if (isActive(view)) {
    return (
      <Button {...look} onClick={showRuns}>
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
            {...look}
            onClick={() =>
              start({ process, period: period.token, dry_run: true }).then((started) => started && showRuns())
            }
          />
        }
      >
        <EyeIcon data-icon="inline-start" />
        Podgląd bez zapisu
      </TooltipTrigger>
      <TooltipContent>{step.preview_hint}</TooltipContent>
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
