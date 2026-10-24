import { MessageSquarePlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useDadNote } from "@/lib/dad-note"

const ABOUT_RUN = "Napisz do Maksa o tym Uruchomieniu"

/** Ikona „Napisz do Maksa” w nagłówku: Uwaga taty ogólna. */
export function WriteToMaks() {
  const open = useDadNote()

  return (
    <Tooltip>
      <TooltipTrigger
        render={<Button variant="ghost" size="icon" aria-label="Napisz do Maksa" onClick={() => open()} />}
      >
        <MessageSquarePlusIcon />
      </TooltipTrigger>
      <TooltipContent>Napisz do Maksa</TooltipContent>
    </Tooltip>
  )
}

/** Ta sama ikona przy zakończonym Uruchomieniu z Centrum: Uwaga od razu przypięta do niego. */
export function WriteAboutRun({ runId, className }: { runId: string; className?: string }) {
  const open = useDadNote()

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className={className}
            aria-label={ABOUT_RUN}
            onClick={() => open(runId)}
          />
        }
      >
        <MessageSquarePlusIcon />
      </TooltipTrigger>
      <TooltipContent>{ABOUT_RUN}</TooltipContent>
    </Tooltip>
  )
}
