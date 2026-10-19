import { CheckIcon } from "lucide-react"
import { cn } from "cn"

import type { PeriodRow } from "@/api/centrum"

const STEPS = ["Plik zbiorczy", "Uzupełnienie w Excelu", "Rozliczenia pracowników"] as const

// Ile kroków drogi okresu jest za tatą przy danym Statusie okresu (sama prezentacja statusu).
const DONE: Record<PeriodRow["status"], number> = {
  no_period_files: 0,
  collective_file_prepared: 1,
  worker_settlements_ready: STEPS.length,
}

/** Droga okresu w trzech krokach: ikona stanu zamiast zdań. */
export function PeriodPath({ status }: { status: PeriodRow["status"] }) {
  const done = DONE[status]

  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Droga okresu">
      {STEPS.map((step, index) => {
        const stage = index < done ? "done" : index === done ? "now" : "later"

        return (
          <li key={step} className="flex items-center gap-2" aria-current={stage === "now" ? "step" : undefined}>
            {index > 0 ? (
              <span
                aria-hidden
                className={cn("h-px w-6 bg-border", stage !== "later" && "bg-foreground/40")}
              />
            ) : null}
            <span
              data-stage={stage}
              className="flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium tabular-nums data-[stage=done]:border-transparent data-[stage=done]:bg-secondary data-[stage=now]:border-foreground"
            >
              {stage === "done" ? (
                <CheckIcon className="size-3.5 text-success" aria-label="zrobione" />
              ) : (
                index + 1
              )}
            </span>
            <span
              className={cn(
                "text-sm whitespace-nowrap",
                stage === "later" ? "text-muted-foreground" : "font-medium"
              )}
            >
              {step}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
