import { failureMessage } from "@/api/client"
import { openOrderRegister, openPeriodPath, type OpenTarget } from "@/api/centrum"
import { toast } from "@/components/ui/toast"

// Tata klika dwa razy z przyzwyczajenia i stuka dwa razy w ekran dotykowy, a Excel i Eksplorator otwierają się
// dopiero po chwili: powtórne kliknięcie tego samego pliku do tego czasu to ta sama prośba, nie drugie okno.
const REPEAT_IGNORED_MS = 1500

// Plik albo folder taty, który właśnie się otwiera, i kiedy kończy się ignorowanie powtórzeń;
// `Infinity`, dopóki serwer nie odpowie.
const opening = new Map<string, number>()

/** Otwiera plik okresu w Excelu albo folder; Excel startuje kilka sekund, więc powiadomienie potwierdza kliknięcie. */
export function openAndConfirm(token: string, target: OpenTarget, onFailure: () => void) {
  confirmOpening(`${token}/${target}`, () => openPeriodPath(token, target), onFailure)
}

/** Otwiera Rejestr zleceń z Ustawień taty, z tym samym potwierdzeniem co pliki okresu. */
export function openOrderRegisterAndConfirm() {
  confirmOpening("rejestr-zlecen", openOrderRegister, () => undefined)
}

function confirmOpening(key: string, open: () => Promise<{ name: string }>, onFailure: () => void) {
  if ((opening.get(key) ?? 0) > performance.now()) {
    return
  }

  opening.set(key, Infinity)
  open()
    .then(
      (opened) => toast.add({ title: "Otwieram", description: opened.name }),
      (failure: Error) => {
        toast.add({ title: "Nie udało się otworzyć", description: failureMessage(failure), type: "error" })
        onFailure()
      }
    )
    .finally(() => opening.set(key, performance.now() + REPEAT_IGNORED_MS))
}
