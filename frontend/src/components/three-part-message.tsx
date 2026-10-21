import type * as React from "react"
import { MapPinIcon, OctagonXIcon, StethoscopeIcon, TriangleAlertIcon, WrenchIcon } from "lucide-react"

import type { Message } from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"

export type MessageKind = "stop" | "warning" | "diagnosis"

const LABELS: Record<MessageKind, string> = {
  stop: "Zatrzymanie",
  warning: "Ostrzeżenie",
  diagnosis: "Wyjaśnienie Diagnozy",
}

const ICONS: Record<MessageKind, React.ReactNode> = {
  stop: <OctagonXIcon />,
  warning: <TriangleAlertIcon className="text-warning!" />,
  diagnosis: <StethoscopeIcon className="text-muted-foreground!" />,
}

/**
 * Komunikat w trzech częściach jako baner: „Co się stało” jest tytułem,
 * „Gdzie” i „Co zrobić” to dwa wiersze z ikonami. Opis jest spokojny, nie cały czerwony. Zatrzymanie
 * i ostrzeżenie różnią się ikoną i kolorem tytułu, a wyjaśnienie Diagnozy jest spokojne, bez czerwieni;
 * `action` to akcja przy banerze.
 */
export function ThreePartMessage({
  message,
  kind,
  action,
}: {
  message: Message
  kind: MessageKind
  action?: React.ReactNode
}) {
  return (
    <Alert
      variant={kind === "stop" ? "destructive" : "default"}
      className="wejscie p-4"
      aria-label={LABELS[kind]}
    >
      {ICONS[kind]}
      <AlertTitle className="leading-snug data-[action=true]:pr-48" data-action={action !== undefined}>
        {message.what}
      </AlertTitle>
      <AlertDescription className="mt-2 flex flex-col gap-1.5 text-foreground/80!">
        <span className="flex gap-2">
          <MapPinIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
          {message.where}
        </span>
        <span className="flex gap-2">
          <WrenchIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
          {message.action}
        </span>
      </AlertDescription>
      {action === undefined ? null : <AlertAction className="top-3 right-3">{action}</AlertAction>}
    </Alert>
  )
}
