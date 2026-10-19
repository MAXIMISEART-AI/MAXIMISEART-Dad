import { CalendarRangeIcon, CircleCheckIcon, FolderXIcon } from "lucide-react"

import type { PeriodRow } from "@/api/centrum"
import { PeriodPath } from "@/components/period-path"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { fullDate } from "@/lib/format"

/**
 * „Następny krok” zawsze dla ostatniego pełnego okresu: krótki tytuł, fakty z ikonami i droga okresu.
 * Akcję główną („Podgląd bez zapisu”) dokłada Przygotowanie pliku zbiorczego z Centrum (#98).
 */
export function NextStepCard({ period }: { period: PeriodRow }) {
  const closed = period.next_step.action === "none"

  return (
    <Card className="bg-linear-to-br from-muted/60 to-card" role="region" aria-label="Następny krok">
      <CardContent className="flex flex-col gap-4 py-2">
        <Badge variant="outline">Następny krok</Badge>
        <h2 className="flex items-center gap-3 text-3xl font-semibold tracking-tight">
          {closed ? <CircleCheckIcon className="size-7 text-success" aria-hidden /> : null}
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
