import { MapPinIcon, OctagonXIcon, TriangleAlertIcon, WrenchIcon } from "lucide-react"

import type { Message } from "@/api/centrum"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

/**
 * Komunikat w trzech częściach (ta sama treść co w terminalu) jako baner: „Co się stało” jest tytułem,
 * „Gdzie” i „Co zrobić” to dwa wiersze z ikonami. Opis jest spokojny, nie cały czerwony.
 */
export function ThreePartMessage({
  message,
  kind,
}: {
  message: Message
  kind: "stop" | "warning"
}) {
  return (
    <Alert variant={kind === "stop" ? "destructive" : "default"} className="wejscie p-4">
      {kind === "stop" ? <OctagonXIcon /> : <TriangleAlertIcon className="text-warning!" />}
      <AlertTitle className="leading-snug">{message.what}</AlertTitle>
      <AlertDescription className="mt-2 flex flex-col gap-1.5 text-foreground/80!">
        <span className="flex gap-2">
          <MapPinIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
          {message.where}
        </span>
        <span className="flex gap-2">
          <WrenchIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
          {message.action}
        </span>
      </AlertDescription>
    </Alert>
  )
}
