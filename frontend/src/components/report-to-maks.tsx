import * as React from "react"
import { CircleCheckIcon, ClockIcon, RotateCcwIcon, SendIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import type { ReportDraft, RunOutcome } from "@/api/centrum"
import { Disclosure } from "@/components/disclosure"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ThreePartMessage } from "@/components/three-part-message"
import { toast } from "@/components/ui/toast"

type ReportState = NonNullable<RunOutcome["report"]>

/**
 * Zgłoszenie do Maksa (przy Zatrzymaniu albo nieudanej Aktualizacji narzędzia): podgląd i „Wyślij do Maksa”,
 * potwierdzenie po wysłaniu albo Komunikat z „Spróbuj ponownie”, gdy Zgłoszenie czeka w pliku. Gdy ten problem
 * ma już otwarte Zgłoszenie, zamiast przycisku jest „już wysłane i czeka na naprawę”. Stan liczy serwer, a `send`
 * prosi go o wysyłkę; `draft` przy Zatrzymaniu jest dopiero po Diagnozie, więc przed nią widać tylko
 * potwierdzenie albo zapisane Zgłoszenie.
 */
export function ReportToMaks({
  send: sendReport,
  report,
  draft,
  primary,
}: {
  send: () => Promise<ReportState>
  report: ReportState
  draft: ReportDraft | null
  /** „Wyślij do Maksa” jest głównym przyciskiem, gdy przyczynę usuwa Maks. */
  primary: boolean
}) {
  const [sending, setSending] = React.useState(false)
  const [answer, setAnswer] = React.useState<ReportState | null>(null)
  const state = answer ?? report

  const send = () => {
    setSending(true)

    sendReport()
      .then(setAnswer, (failure: Error) => {
        toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
      })
      .finally(() => setSending(false))
  }

  if (state.state === "sent") {
    return (
      <p role="status" className="wejscie flex items-center gap-2 text-sm">
        <CircleCheckIcon className="size-4 text-success" aria-hidden />
        Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.
      </p>
    )
  }

  if (state.state === "waiting") {
    return (
      <p role="status" className="wejscie flex items-center gap-2 text-sm">
        <ClockIcon className="size-4 text-muted-foreground" aria-hidden />
        Zgłoszenie tego problemu już jest wysłane i czeka na naprawę.
      </p>
    )
  }

  if (state.state === "saved") {
    return (
      <div className="flex flex-col gap-2">
        <ThreePartMessage
          message={state.message}
          kind="warning"
          action={
            <Button size="sm" variant="outline" onClick={send} disabled={sending}>
              {sending ? <Spinner data-icon="inline-start" /> : <RotateCcwIcon data-icon="inline-start" />}
              Spróbuj ponownie
            </Button>
          }
        />
        {draft === null ? null : <Preview draft={draft} />}
      </div>
    )
  }

  if (draft === null) {
    return null
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button size="sm" variant={primary ? "default" : "outline"} onClick={send} disabled={sending}>
        {sending ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
        Wyślij do Maksa
      </Button>
      <Preview draft={draft} />
    </div>
  )
}

/** Dokładna treść Zgłoszenia, zwinięta: tata widzi przed wysłaniem, co dostanie Maks. */
function Preview({ draft }: { draft: ReportDraft }) {
  return (
    <Disclosure label="Co zostanie wysłane" className="w-full">
      <figure aria-label="Treść Zgłoszenia" className="mt-1 rounded-md border bg-muted/40 p-3 text-xs">
        <figcaption className="mb-2 font-medium">{draft.title}</figcaption>
        <pre className="max-h-80 overflow-auto font-mono whitespace-pre-wrap text-muted-foreground">{draft.body}</pre>
      </figure>
    </Disclosure>
  )
}
