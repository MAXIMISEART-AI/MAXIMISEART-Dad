import { failureMessage } from "@/api/client"
import { openPeriodPath, openWorkerSettlement, type OpenRequest, type WorkerSettlementRequest } from "@/api/centrum"
import { toast } from "@/components/ui/toast"

// Tata klika dwa razy z przyzwyczajenia i stuka dwa razy w ekran dotykowy, a Excel i Eksplorator otwierają się
// dopiero po chwili: powtórne kliknięcie tego samego pliku do tego czasu to ta sama prośba, nie drugie okno.
const REPEAT_IGNORED_MS = 1500

/** Plik albo folder okresu z jego rodzaju albo Rozliczenie pracownika jednego Wykonawcy: treść żądania do serwera. */
export type OpenedInPeriod = OpenRequest | WorkerSettlementRequest

// Plik albo folder okresu (`token/target` albo `token/pracownik/worker`), który właśnie się otwiera, i kiedy
// kończy się ignorowanie powtórzeń; `Infinity`, dopóki serwer nie odpowie.
const opening = new Map<string, number>()

/** Otwiera plik okresu w Excelu albo folder; Excel startuje kilka sekund, więc powiadomienie potwierdza kliknięcie. */
export function openAndConfirm(token: string, what: OpenedInPeriod, onFailure: () => void = () => undefined) {
  const key = "worker" in what ? `${token}/pracownik/${what.worker}` : `${token}/${what.target}`

  if ((opening.get(key) ?? 0) > performance.now()) {
    return
  }

  opening.set(key, Infinity)
  const request = "worker" in what ? openWorkerSettlement(token, what.worker) : openPeriodPath(token, what.target)
  request
    .then(
      (opened) => toast.add({ title: "Otwieram", description: opened.name }),
      (failure: Error) => {
        toast.add({ title: "Nie udało się otworzyć", description: failureMessage(failure), type: "error" })
        onFailure()
      }
    )
    .finally(() => opening.set(key, performance.now() + REPEAT_IGNORED_MS))
}
