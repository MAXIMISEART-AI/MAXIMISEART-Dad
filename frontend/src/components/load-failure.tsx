import * as React from "react"
import { cn } from "cn"
import { RotateCwIcon } from "lucide-react"

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"

/**
 * Nieudany odczyt strony z serwera: co się nie odczytało, Komunikat i „Spróbuj ponownie”, które czyta od nowa.
 * Dopóki ponowny odczyt jest w drodze, przycisk czeka; udany odczyt zastępuje ten baner treścią strony.
 */
export function LoadFailure({
  what,
  message,
  reload,
  className,
}: {
  /** Dopełniacz po „Nie udało się odczytać”, np. „okresów”. */
  what: string
  message: string
  reload: () => Promise<void>
  className?: string
}) {
  const [retrying, setRetrying] = React.useState(false)

  const retry = () => {
    setRetrying(true)
    reload().finally(() => setRetrying(false))
  }

  return (
    <Alert variant="destructive" className={cn(className ?? "wejscie", "has-data-[slot=alert-action]:pr-44")}>
      <AlertTitle>Nie udało się odczytać {what}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
      <AlertAction className="top-1/2 -translate-y-1/2">
        <Button variant="outline" size="sm" className="text-foreground" disabled={retrying} onClick={retry}>
          {retrying ? <Spinner data-icon="inline-start" /> : <RotateCwIcon data-icon="inline-start" />}
          Spróbuj ponownie
        </Button>
      </AlertAction>
    </Alert>
  )
}
