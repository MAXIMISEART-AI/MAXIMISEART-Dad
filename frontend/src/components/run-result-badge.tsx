import { CircleCheckIcon, OctagonXIcon, TriangleAlertIcon } from "lucide-react"

import type { ProcessRun, ResultCounts } from "@/api/centrum"
import { Badge } from "@/components/ui/badge"

// Wynik Uruchomienia procesu zawsze z ikoną i słowem, nigdy samym kolorem.
export function RunResultBadge({ result }: { result: ProcessRun["result"] }) {
  switch (result) {
    case "OK":
      return (
        <Badge variant="secondary">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          OK
        </Badge>
      )
    case "WYMAGA_SPRAWDZENIA":
      return (
        <Badge variant="outline">
          <TriangleAlertIcon data-icon="inline-start" className="text-warning" />
          Do sprawdzenia
        </Badge>
      )
    case "BLAD_KRYTYCZNY":
      return (
        <Badge variant="destructive">
          <OctagonXIcon data-icon="inline-start" />
          Zatrzymano
        </Badge>
      )
  }
}

/** `3 do sprawdzenia · 1 zatrzymane`: dopisek pod liczbą wyników OK. */
export function otherResults(results: ResultCounts): string {
  return `${results.needs_review} do sprawdzenia · ${results.critical} zatrzymane`
}
