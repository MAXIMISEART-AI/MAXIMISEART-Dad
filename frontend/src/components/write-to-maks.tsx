import * as React from "react"
import { cn } from "cn"
import { CircleCheckIcon, ClockIcon, MessageSquarePlusIcon, SendIcon, type LucideIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import { draftDadNote, sendDadNote, type DadNoteDraft, type DadNoteState } from "@/api/centrum"
import { zDadNoteRequest } from "@/api/generated/zod.gen"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

const TITLE_MAX_LENGTH = zDadNoteRequest.shape.title.toJSONSchema().maxLength

const BODY_MAX_LENGTH = zDadNoteRequest.shape.body.toJSONSchema().maxLength

// Szkic dopiero po krótkiej przerwie w pisaniu: zapytanie na każdy klawisz zapychałoby pomiar widoku.
const DRAFT_PAUSE_MS = 150

const ANSWERS: Record<DadNoteState["state"], { icon: LucideIcon; tone: string; text: string }> = {
  sent: { icon: CircleCheckIcon, tone: "text-success", text: "Uwaga wysłana do Maksa." },
  waiting: { icon: ClockIcon, tone: "text-muted-foreground", text: "Wyślę do Maksa, gdy będzie internet." },
}

/** Ikona „Napisz do Maksa” w nagłówku i okno Uwagi taty ogólnej; każde otwarcie to nowa Uwaga. */
export function WriteToMaks() {
  const [open, setOpen] = React.useState(false)
  const [opening, setOpening] = React.useState(0)

  const openNote = () => {
    setOpening((count) => count + 1)
    setOpen(true)
  }

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={<Button variant="ghost" size="icon" aria-label="Napisz do Maksa" onClick={openNote} />}
        >
          <MessageSquarePlusIcon />
        </TooltipTrigger>
        <TooltipContent>Napisz do Maksa</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="gap-5 sm:max-w-lg">
          <DadNoteForm key={opening} close={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </>
  )
}

function DadNoteForm({ close }: { close: () => void }) {
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [sending, setSending] = React.useState(false)
  const [answer, setAnswer] = React.useState<DadNoteState | null>(null)
  const { draft, current } = useDraft(title, body)

  if (answer !== null) {
    return <Answer state={answer} close={close} />
  }

  const send = (event: React.FormEvent) => {
    event.preventDefault()
    setSending(true)

    sendDadNote({ title, body })
      .then(setAnswer, (failure: Error) => {
        toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
      })
      .finally(() => setSending(false))
  }

  return (
    <form onSubmit={send} className="flex min-h-0 flex-col gap-5">
      <DialogHeader>
        <DialogTitle>Napisz do Maksa</DialogTitle>
      </DialogHeader>
      <Field>
        <FieldLabel htmlFor="uwaga-tytul">Tytuł</FieldLabel>
        <Input
          id="uwaga-tytul"
          required
          autoFocus
          maxLength={TITLE_MAX_LENGTH}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor="uwaga-tresc">
          Treść <span className="font-normal text-muted-foreground">(niekonieczna)</span>
        </FieldLabel>
        <Textarea
          id="uwaga-tresc"
          rows={3}
          maxLength={BODY_MAX_LENGTH}
          className="max-h-48"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
      </Field>
      <Preview draft={draft} />
      <DialogFooter>
        <Button type="submit" disabled={title.trim() === "" || !current || sending}>
          {sending ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
          Wyślij
        </Button>
      </DialogFooter>
    </form>
  )
}

type Drafted = { title: string; body: string; draft: DadNoteDraft }

/**
 * Szkic issue od serwera dla tego, co tata właśnie napisał. Poprzedni szkic zostaje na ekranie, dopóki nie
 * przyjdzie nowszy, a odpowiedź na tekst, który tata już zmienił, przepada. `current` mówi, czy szkic na ekranie
 * jest z pól, które teraz wyśle „Wyślij”: bez tego tata mógłby wysłać coś innego, niż widzi w „Maks dostanie”.
 */
function useDraft(title: string, body: string) {
  const [drafted, setDrafted] = React.useState<Drafted | null>(null)

  React.useEffect(() => {
    let wanted = true

    const pause = window.setTimeout(() => {
      draftDadNote({ title, body }).then(
        (draft) => {
          if (wanted) {
            setDrafted({ title, body, draft })
          }
        },
        () => undefined
      )
    }, DRAFT_PAUSE_MS)

    return () => {
      wanted = false
      window.clearTimeout(pause)
    }
  }, [title, body])

  return {
    draft: drafted?.draft ?? null,
    current: drafted !== null && drafted.title === title && drafted.body === body,
  }
}

/** „Maks dostanie”: tytuł i treść issue dokładnie tak, jak złożył je serwer. */
function Preview({ draft }: { draft: DadNoteDraft | null }) {
  const title = draft?.title ?? ""

  return (
    <figure aria-label="Co dostanie Maks" className="flex min-h-0 flex-col gap-1 overflow-y-auto rounded-lg bg-muted/50 p-3 text-sm">
      <figcaption className="text-xs text-muted-foreground">Maks dostanie</figcaption>
      <p className={cn("font-medium break-words", title === "" && "text-muted-foreground/60")}>
        {title === "" ? "Tytuł" : title}
      </p>
      {draft === null ? null : (
        <p className="max-h-48 overflow-y-auto break-words whitespace-pre-wrap text-muted-foreground">{draft.body}</p>
      )}
    </figure>
  )
}

function Answer({ state, close }: { state: DadNoteState; close: () => void }) {
  const { icon: Icon, tone, text } = ANSWERS[state.state]

  return (
    <>
      <DialogTitle className="sr-only">Napisz do Maksa</DialogTitle>
      <div className="wejscie flex flex-col items-center gap-3 py-6 text-center">
        <Icon className={cn("size-8", tone)} aria-hidden />
        <p role="status" className="text-base font-medium">
          {text}
        </p>
        <Button variant="outline" className="mt-2" onClick={close}>
          Zamknij
        </Button>
      </div>
    </>
  )
}
