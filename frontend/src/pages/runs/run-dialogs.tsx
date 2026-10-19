import * as React from "react"
import {
  ChevronDownIcon,
  InfoIcon,
  MapPinIcon,
  PlayIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import type { Decision } from "@/api/centrum"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { CountTiles } from "@/pages/runs/count-tiles"

/**
 * Potwierdzenie zapisu (RUN): przypomnienie o zamknięciu pliku w Excelu i, gdy w tej karcie nie było
 * udanego podglądu bez zapisu tego okresu, bursztynowa uwaga. Bez podglądu „Uruchom” jest dozwolone.
 */
export function ConfirmRunDialog({
  open,
  onOpenChange,
  title,
  period,
  reminder,
  previewed,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  period: string
  reminder: string
  previewed: boolean
  onConfirm: () => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <PlayIcon />
          </AlertDialogMedia>
          <AlertDialogTitle>Uruchomić z zapisem?</AlertDialogTitle>
          <AlertDialogDescription className="tabular-nums">
            {title} · okres {period}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2 text-sm">
          <span className="flex items-center gap-2">
            <InfoIcon className="size-4 text-muted-foreground" aria-hidden />
            {reminder}
          </span>
          {previewed ? null : (
            <span className="flex items-center gap-2 text-warning">
              <TriangleAlertIcon className="size-4" aria-hidden />
              Nie było podglądu bez zapisu
            </span>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Anuluj</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              onOpenChange(false)
              onConfirm()
            }}
          >
            Uruchom
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/**
 * Decyzja taty, na którą czeka Uruchomienie procesu (np. niepełny okres). Okno trwa tak długo, jak
 * serwer czeka, więc wraca po odświeżeniu karty. Fokus startuje na bezpiecznej opcji „Przerwij bez zapisu”.
 */
export function DecisionDialog({
  decision,
  onDecide,
}: {
  decision: Decision
  onDecide: (answer: "continue" | "abort") => Promise<void>
}) {
  const abort = React.useRef<HTMLButtonElement>(null)
  const [sending, setSending] = React.useState(false)
  const message = decision.message

  const decide = (answer: "continue" | "abort") => {
    setSending(true)
    onDecide(answer).finally(() => setSending(false))
  }

  return (
    <AlertDialog open>
      <AlertDialogContent initialFocus={abort} className="data-[size=default]:sm:max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogMedia className="text-warning">
            <TriangleAlertIcon />
          </AlertDialogMedia>
          <AlertDialogTitle>{decision.question}</AlertDialogTitle>
          {message === null ? null : <AlertDialogDescription>{message.what}</AlertDialogDescription>}
        </AlertDialogHeader>
        {decision.count_groups.map((group) => (
          <CountTiles key={group.title} title={group.title} counts={group.counts} />
        ))}
        {message === null ? null : (
          <Collapsible className="text-sm">
            <CollapsibleTrigger className="group flex items-center gap-1.5 rounded-sm text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              Gdzie i co zrobić
              <ChevronDownIcon
                className="size-4 transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
                aria-hidden
              />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2 flex flex-col gap-1.5 text-foreground/80 transition-opacity duration-150 data-[starting-style]:opacity-0 data-[ending-style]:opacity-0">
              {message.where === null ? null : (
                <span className="flex gap-2">
                  <MapPinIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
                  {message.where}
                </span>
              )}
              {message.action === null ? null : (
                <span className="flex gap-2">
                  <WrenchIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
                  {message.action}
                </span>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel ref={abort} disabled={sending} onClick={() => decide("abort")}>
            Przerwij bez zapisu
          </AlertDialogCancel>
          <AlertDialogAction disabled={sending} onClick={() => decide("continue")}>
            Kontynuuj
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
