import { CalendarRangeIcon, CircleCheckIcon, FolderXIcon } from "lucide-react"

import type { PeriodRow } from "@/api/centrum"
import { PeriodPath } from "@/components/period-path"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { fullDate } from "@/lib/format"
import { PreviewAction, stepProcess } from "@/pages/periods/prepare-actions"

/**
 * „Następny krok” zawsze dla ostatniego pełnego okresu: krótki tytuł, fakty z ikonami i droga okresu.
 * Gdy okres ma następny krok (Przygotowanie pliku zbiorczego albo Przebieg rozliczeń), jedyną akcją
 * główną strony jest „Podgląd bez zapisu” tego procesu.
 */
export function NextStepCard({ period }: { period: PeriodRow }) {
  const process = stepProcess(period.next_step)

  return (
    <Card className="bg-linear-to-br from-muted/60 to-card" role="region" aria-label="Następny krok">
      <CardContent className="relative flex flex-col gap-4 py-2">
        {process === null ? null : (
          <div className="absolute top-1/2 right-4 -translate-y-1/2">
            <PreviewAction period={period} process={process} />
          </div>
        )}
        <Badge variant="outline">Następny krok</Badge>
        <h2 className="flex items-center gap-3 text-3xl font-semibold tracking-tight">
          {process === null ? <CircleCheckIcon className="size-7 text-success" aria-hidden /> : null}
          {period.next_step.label}
        </h2>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground [&_svg]:size-4">
          <span className="flex items-center gap-1.5 font-medium text-foreground tabular-nums">
            <CalendarRangeIcon aria-hidden />
            {period.token}
          </span>
          <span className="tabular-nums">
            wt {fullDate(period.tuesday)} – pon {fullDate(period.monday)}
          </span>
          {period.period_folder_exists ? null : (
            <span className="flex items-center gap-1.5">
              <FolderXIcon aria-hidden />
              Brak Folderu okresu
            </span>
          )}
        </div>
        <PeriodPath status={period.status} />
        <p className="text-sm text-muted-foreground">{period.next_step.hint}</p>
      </CardContent>
    </Card>
  )
}
