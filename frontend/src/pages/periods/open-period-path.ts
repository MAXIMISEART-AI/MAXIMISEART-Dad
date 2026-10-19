import { failureMessage } from "@/api/client"
import { openPeriodPath, type OpenTarget } from "@/api/centrum"
import { toast } from "@/components/ui/toast"

/** Otwiera plik okresu w Excelu albo folder; Excel startuje kilka sekund, więc powiadomienie potwierdza kliknięcie. */
export function openAndConfirm(token: string, target: OpenTarget, onFailure: () => void) {
  openPeriodPath(token, target).then(
    (opened) => toast.add({ title: "Otwieram", description: opened.name }),
    (failure: Error) => {
      toast.add({ title: "Nie udało się otworzyć", description: failureMessage(failure), type: "error" })
      onFailure()
    }
  )
}
