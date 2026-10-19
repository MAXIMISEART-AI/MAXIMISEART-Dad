import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import type { NextStep, PeriodRow, RunRequest } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { isActive, useRuns } from "@/lib/runs"

const RUNS_PAGE = "#/uruchomienia"

/** Proces, który robi następny krok okresu; „none” (okres zamknięty) nie ma procesu. */
const STEP_PROCESSES: Record<Exclude<NextStep["action"], "none">, RunRequest["process"]> = {
  prepare_collective_file: "preparation",
  create_worker_settlements: "settlement",
}

/** Podpowiedź „Podgląd bez zapisu”: co zobaczy tata, zanim cokolwiek zapisze. */
export const PREVIEW_HINTS: Record<RunRequest["process"], string> = {
  preparation: "Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.",
  settlement: "Nic nie zostanie zapisane. Zobaczysz plan plików każdego Wykonawcy.",
}

/** Proces następnego kroku okresu albo `null`, gdy okres jest zamknięty. */
export function stepProcess(step: NextStep): RunRequest["process"] | null {
  return step.action === "none" ? null : STEP_PROCESSES[step.action]
}

function showRuns() {
  window.location.hash = RUNS_PAGE
}

/**
 * Akcja główna karty „Następny krok”: podgląd bez zapisu procesu następnego kroku od razu,
 * a w trakcie Uruchomienia przejście do podglądu na żywo.
 */
export function PreviewAction({ period, process }: { period: PeriodRow; process: RunRequest["process"] }) {
  const { view, start } = useRuns()

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
      <TooltipContent>{PREVIEW_HINTS[process]}</TooltipContent>
    </Tooltip>
  )
}

/** Następny krok w wierszu Tablicy okresów: przejście do Uruchomień z tym procesem i okresem do wybrania. */
export function PrepareLink({ period, process }: { period: PeriodRow; process: RunRequest["process"] }) {
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
