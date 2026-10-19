import type * as React from "react"
import { MapPinIcon, OctagonXIcon, TriangleAlertIcon, WrenchIcon } from "lucide-react"

import type { RunMessage } from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"

/**
 * Komunikat w trzech częściach, z tą samą treścią co w terminalu: „Co się stało” jako tytuł,
 * „Gdzie” i „Co zrobić” jako dwa wiersze z ikonami. Zatrzymanie i ostrzeżenie różnią się ikoną i kolorem tytułu.
 */
export function ThreePartMessage({
  message,
  kind,
  action,
}: {
  message: RunMessage
  kind: "stop" | "warning"
  action?: React.ReactNode
}) {
  return (
    <Alert
      variant={kind === "stop" ? "destructive" : "default"}
      className="wejscie p-4"
      aria-label={kind === "stop" ? "Zatrzymanie" : "Ostrzeżenie"}
    >
      {kind === "stop" ? <OctagonXIcon /> : <TriangleAlertIcon className="text-warning!" />}
      <AlertTitle className="leading-snug data-[action=true]:pr-48" data-action={action !== undefined}>
        {message.what}
      </AlertTitle>
      {message.where === null && message.action === null ? null : (
        <AlertDescription className="mt-2 flex flex-col gap-1.5 text-foreground/80!">
          {message.where === null ? null : (
            <span className="flex gap-2">
              <MapPinIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
              {message.where}
            </span>
          )}
          {message.action === null ? null : (
            <span className="flex gap-2">
              <WrenchIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
              {message.action}
            </span>
          )}
        </AlertDescription>
      )}
      {action === undefined ? null : <AlertAction className="top-3 right-3">{action}</AlertAction>}
    </Alert>
  )
}
