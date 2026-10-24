import * as React from "react"
import { cn } from "cn"
import { CircleCheckIcon, ClockIcon, SendIcon, type LucideIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import {
  draftDadNote,
  getDadNoteRuns,
  sendDadNote,
  type DadNoteDraft,
  type DadNoteRequest,
  type DadNoteState,
  type ProcessRun,
} from "@/api/centrum"
import { zDadNoteRequest } from "@/api/generated/zod.gen"
import { DadNoteRuns, type PinnableRun } from "@/components/dad-note-runs"
import { SegmentedFilter, type FilterOption } from "@/components/segmented-filter"
import { Button } from "@/components/ui/button"
import { DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldLabel, FieldTitle } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"
import type { Resource } from "@/lib/use-resource"

const TITLE_MAX_LENGTH = zDadNoteRequest.shape.title.toJSONSchema().maxLength

const BODY_MAX_LENGTH = zDadNoteRequest.shape.body.toJSONSchema().maxLength

// Szkic dopiero po krótkiej przerwie w pisaniu: zapytanie na każdy klawisz zapychałoby pomiar widoku.
const DRAFT_PAUSE_MS = 150

const ANSWERS: Record<DadNoteState["state"], { icon: LucideIcon; tone: string; text: string }> = {
  sent: { icon: CircleCheckIcon, tone: "text-success", text: "Uwaga wysłana do Maksa." },
  waiting: { icon: ClockIcon, tone: "text-muted-foreground", text: "Wyślę do Maksa, gdy będzie internet." },
}

type Scope = "general" | "run"

const SCOPES: ReadonlyArray<FilterOption<Scope>> = [
  { value: "general", label: "Ogólna" },
  { value: "run", label: "Do Uruchomienia" },
]

/**
 * Jedna Uwaga taty; okno montuje formularz od nowa przy każdym otwarciu. `openedFrom` to Uruchomienie, z którego
 * karty albo wiersza Historii tata otworzył okno: Uwaga jest wtedy od razu „Do Uruchomienia” z nim zaznaczonym.
 */
export function DadNoteForm({ openedFrom, close }: { openedFrom: string | null; close: () => void }) {
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [scope, setScope] = React.useState<Scope>(openedFrom === null ? "general" : "run")
  const [checked, setChecked] = React.useState(openedFrom)
  const [sending, setSending] = React.useState(false)
  const [answer, setAnswer] = React.useState<DadNoteState | null>(null)
  const runs = usePinnableRuns(openedFrom)
  const note = React.useMemo(() => noteFor(title, body, scope, runs, checked), [title, body, scope, runs, checked])

  const { shown, sendable } = useDraft(note)

  if (answer !== null) {
    return <Answer state={answer} close={close} />
  }

  const send = (event: React.FormEvent) => {
    event.preventDefault()

    if (sendable === null) {
      return
    }

    setSending(true)

    sendDadNote(sendable)
      .then(setAnswer, (failure: Error) => {
        toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
      })
      .finally(() => setSending(false))
  }

  return (
    <form onSubmit={send} className="flex flex-col gap-5">
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
      <Field>
        <FieldTitle>Dotyczy</FieldTitle>
        <SegmentedFilter label="Dotyczy" options={SCOPES} value={scope} onChange={setScope} />
        {scope === "run" ? <DadNoteRuns runs={runs} checked={checked} onCheck={setChecked} /> : null}
      </Field>
      <Preview shown={shown} />
      <DialogFooter>
        <Button type="submit" disabled={title.trim() === "" || sendable === null || sending}>
          {sending ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
          Wyślij
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Uruchomienia do wyboru, czytane raz na otwarcie okna (z Uruchomieniem, z którego tata je otworzył). */
function usePinnableRuns(selected: string | null): Resource<ReadonlyArray<PinnableRun>> {
  const [runs, setRuns] = React.useState<Resource<ReadonlyArray<PinnableRun>>>({ state: "loading" })

  React.useEffect(() => {
    let wanted = true

    getDadNoteRuns(selected).then(
      (list) => {
        if (wanted) {
          setRuns({ state: "ready", data: list.filter(isPinnable) })
        }
      },
      (failure: Error) => {
        if (wanted) {
          setRuns({ state: "failed", message: failureMessage(failure) })
        }
      }
    )

    return () => {
      wanted = false
    }
  }, [selected])

  return runs
}

function isPinnable(run: ProcessRun): run is PinnableRun {
  return run.run_id !== null
}

/** Uwaga do szkicu i do wysłania; `null`, gdy przy „Do Uruchomienia” nie jest zaznaczone Uruchomienie z listy. */
function noteFor(
  title: string,
  body: string,
  scope: Scope,
  runs: Resource<ReadonlyArray<PinnableRun>>,
  checked: string | null
): DadNoteRequest | null {
  if (scope === "general") {
    return { title, body, run_id: null }
  }

  const pinned = runs.state === "ready" ? runs.data.find((run) => run.run_id === checked) : undefined

  return pinned === undefined ? null : { title, body, run_id: pinned.run_id }
}

type Shown = { kind: "draft"; draft: DadNoteDraft } | { kind: "failure"; message: string }

type Drafted = { note: DadNoteRequest; shown: Shown }

function sameNote(left: DadNoteRequest, right: DadNoteRequest): boolean {
  return left.title === right.title && left.body === right.body && left.run_id === right.run_id
}

/**
 * Szkic issue od serwera dla tego, co tata właśnie napisał i wybrał. Poprzedni szkic zostaje na ekranie, dopóki nie
 * przyjdzie nowszy, a odpowiedź na Uwagę, którą tata już zmienił, przepada. `sendable` to Uwaga, której szkic jest
 * na ekranie, tylko gdy to dokładnie ta, którą wyśle „Wyślij”: tata nigdy nie wyśle czegoś innego, niż widzi.
 */
function useDraft(note: DadNoteRequest | null) {
  const [drafted, setDrafted] = React.useState<Drafted | null>(null)

  React.useEffect(() => {
    if (note === null) {
      return
    }

    let wanted = true

    const pause = window.setTimeout(() => {
      draftDadNote(note).then(
        (draft) => {
          if (wanted) {
            setDrafted({ note, shown: { kind: "draft", draft } })
          }
        },
        (failure: Error) => {
          if (wanted) {
            setDrafted({ note, shown: { kind: "failure", message: failureMessage(failure) } })
          }
        }
      )
    }, DRAFT_PAUSE_MS)

    return () => {
      wanted = false
      window.clearTimeout(pause)
    }
  }, [note])

  if (note === null || drafted === null) {
    return { shown: null, sendable: null }
  }

  const current = sameNote(drafted.note, note) && drafted.shown.kind === "draft"

  return { shown: drafted.shown, sendable: current ? note : null }
}

/** „Maks dostanie”: tytuł i treść issue dokładnie tak, jak złożył je serwer, albo powód, dla którego ich nie ma. */
function Preview({ shown }: { shown: Shown | null }) {
  const title = shown?.kind === "draft" ? shown.draft.title : ""

  return (
    <figure aria-label="Co dostanie Maks" className="flex flex-col gap-1 rounded-lg bg-muted/50 p-3 text-sm">
      <figcaption className="text-xs text-muted-foreground">Maks dostanie</figcaption>
      <p className={cn("font-medium break-words", title === "" && "text-muted-foreground/60")}>
        {title === "" ? "Tytuł" : title}
      </p>
      {shown === null ? null : (
        <p
          className={cn(
            "max-h-48 overflow-y-auto break-words whitespace-pre-wrap",
            shown.kind === "draft" ? "text-muted-foreground" : "text-destructive"
          )}
        >
          {shown.kind === "draft" ? shown.draft.body : shown.message}
        </p>
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
