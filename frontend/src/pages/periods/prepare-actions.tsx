import { ArrowRightIcon, EyeIcon, PlayIcon } from "lucide-react"

import type { PeriodRow } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { isActive, useRuns } from "@/lib/runs"

const RUNS_PAGE = "#/uruchomienia"

function showRuns() {
  window.location.hash = RUNS_PAGE
}

/**
 * Akcja główna karty „Następny krok” przy Statusie „Brak plików okresu”: podgląd bez zapisu
 * Przygotowania pliku zbiorczego od razu, a w trakcie Uruchomienia przejście do podglądu na żywo.
 */
export function PreviewAction({ period }: { period: PeriodRow }) {
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
              start({ process: "preparation", period: period.token, dry_run: true }).then(
                (started) => started && showRuns()
              )
            }
          />
        }
      >
        <EyeIcon data-icon="inline-start" />
        Podgląd bez zapisu
      </TooltipTrigger>
      <TooltipContent>Nic nie zostanie zapisane. Zobaczysz plan i nazwy obu plików.</TooltipContent>
    </Tooltip>
  )
}

/** Następny krok w wierszu Tablicy okresów: przejście do Uruchomień z tym okresem do wybrania. */
export function PrepareLink({ period }: { period: PeriodRow }) {
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
              setDraft({ process: "preparation", period: period.token })
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
