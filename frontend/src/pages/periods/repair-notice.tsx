import { WrenchIcon } from "lucide-react"

import { getRepairNotice } from "@/api/centrum"
import { Alert, AlertTitle } from "@/components/ui/alert"
import { useResource } from "@/lib/use-resource"

/**
 * Powiadomienie o naprawie: Maks zamknął Zgłoszenie wysłane z tej wersji narzędzia. Serwer sam pyta skrzynkę
 * Zgłoszeń (najwyżej raz na 10 minut) i znika powiadomienie po aktualizacji; brak sieci to po prostu brak powiadomienia.
 */
export function RepairNotice() {
  const { resource: notice } = useResource(getRepairNotice)

  if (notice.state !== "ready" || !notice.data.repaired) {
    return null
  }

  return (
    <Alert role="status" className="wejscie">
      <WrenchIcon className="text-success" aria-hidden />
      <AlertTitle>Maks naprawił zgłoszony problem. Zaktualizuj narzędzie.</AlertTitle>
    </Alert>
  )
}
