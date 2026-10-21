import { WrenchIcon } from "lucide-react"

import { getRepairNotice } from "@/api/centrum"
import { ToolUpdateButton, ToolUpdateStatus } from "@/components/tool-update"
import { Alert, AlertAction, AlertTitle } from "@/components/ui/alert"
import { useResource } from "@/lib/use-resource"

/**
 * Powiadomienie o naprawie: Maks zamknął Zgłoszenie wysłane z tej wersji narzędzia. Serwer sam pyta skrzynkę
 * Zgłoszeń (najwyżej raz na 10 minut); brak sieci to po prostu brak powiadomienia. Przy powiadomieniu jest przycisk
 * `Zaktualizuj narzędzie`: po aktualizacji Centrum startuje w nowej wersji, karta się przeładowuje, a commit jest inny,
 * więc powiadomienia już nie ma.
 */
export function RepairNotice() {
  const { resource: notice } = useResource(getRepairNotice)

  if (notice.state !== "ready" || !notice.data.repaired) {
    return null
  }

  return (
    <div className="flex flex-col gap-3">
      <Alert role="status" className="wejscie">
        <WrenchIcon className="text-success" aria-hidden />
        <AlertTitle className="pr-44">Maks naprawił zgłoszony problem.</AlertTitle>
        <AlertAction className="top-1/2 -translate-y-1/2">
          <ToolUpdateButton primary={false} size="sm" />
        </AlertAction>
      </Alert>
      <ToolUpdateStatus />
    </div>
  )
}
