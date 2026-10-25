import * as React from "react"
import {
  CircleCheckIcon,
  ChevronDownIcon,
  InfoIcon,
  MapPinIcon,
  PlayIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import type { Decision, DecisionAnswer, PeriodChoice } from "@/api/centrum"
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
 * Potwierdzenie zapisu (RUN): przypomnienie o zamknięciu pliku w Excelu i, gdy w historii metryk nie ma
 * udanego podglądu bez zapisu tego okresu (serwer mówi to w wyborze okresu), bursztynowa uwaga. Bez
 * podglądu „Uruchom” jest dozwolone.
 * Gdy proces deklaruje, że „Uruchom” potwierdza Gotowość (Przebieg rozliczeń), okno to mówi i wymienia
 * wiersze Pliku zbiorczego bez ilości; to tylko informacja, „Uruchom” zostaje dozwolone.
 */
export function ConfirmRunDialog({
  open,
  onOpenChange,
  title,
  period,
  reminder,
  confirmsReadiness,
  previewed,
  withoutQuantity,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  period: string
  reminder: string
  confirmsReadiness: boolean
  previewed: boolean
  withoutQuantity: PeriodChoice["without_quantity"]
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
          {confirmsReadiness ? (
            <span className="flex items-center gap-2">
              <CircleCheckIcon className="size-4 text-muted-foreground" aria-hidden />
              „Uruchom” potwierdza Gotowość Pliku zbiorczego
            </span>
          ) : null}
          <WithoutQuantityLine withoutQuantity={withoutQuantity} />
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

/** „1 wiersz”, „3 wiersze”, „12 wierszy”, „22 wiersze” */
function rowsCount(count: number): string {
  if (count === 1) {
    return "1 wiersz"
  }

  const few = [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)

  return `${count} ${few ? "wiersze" : "wierszy"}`
}

/** Wiersze bez ilości okresu; Plik zbiorczy bez odczytu też jest wymieniony, żeby cisza nie znaczyła „nic nie zostało”. */
function WithoutQuantityLine({ withoutQuantity }: { withoutQuantity: PeriodChoice["without_quantity"] }) {
  if (withoutQuantity === null || (withoutQuantity.state === "read" && withoutQuantity.rows.length === 0)) {
    return null
  }

  if (withoutQuantity.state === "unread") {
    return (
      <span className="flex items-center gap-2 text-muted-foreground">
        <InfoIcon className="size-4" aria-hidden />
        Nie udało się sprawdzić wierszy bez ilości
      </span>
    )
  }

  return (
    <span className="flex items-start gap-2 text-warning tabular-nums">
      <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
      {rowsCount(withoutQuantity.rows.length)} bez ilości: {withoutQuantity.rows.join(", ")}
    </span>
  )
}

/**
 * Decyzja taty, na którą czeka Uruchomienie procesu (np. niepełny okres). Okno trwa tak długo, jak
 * serwer czeka, więc wraca po odświeżeniu karty. Fokus startuje na bezpiecznej opcji „Przerwij bez zapisu”.
 * Po wysłanej decyzji przyciski czekają, aż okno zniknie (`deciding`).
 */
export function DecisionDialog({
  decision,
  deciding,
  onDecide,
}: {
  decision: Decision
  deciding: boolean
  onDecide: (answer: DecisionAnswer["answer"]) => void
}) {
  const abort = React.useRef<HTMLButtonElement>(null)
  const message = decision.message

  return (
    <AlertDialog open>
      <AlertDialogContent initialFocus={abort} className="data-[size=default]:sm:max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogMedia className="text-warning">
            <TriangleAlertIcon />
          </AlertDialogMedia>
          <AlertDialogTitle>{decision.question}</AlertDialogTitle>
          <AlertDialogDescription>{message.what}</AlertDialogDescription>
        </AlertDialogHeader>
        <CountTiles title={decision.counts.title} counts={decision.counts.counts} />
        <Collapsible className="text-sm">
          <CollapsibleTrigger className="group flex items-center gap-1.5 rounded-sm text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            Gdzie i co zrobić
            <ChevronDownIcon
              className="size-4 transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
              aria-hidden
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-1.5 pt-2 text-foreground/80">
            <span className="flex gap-2">
              <MapPinIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
              {message.where}
            </span>
            <span className="flex gap-2">
              <WrenchIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
              {message.action}
            </span>
          </CollapsibleContent>
        </Collapsible>
        <AlertDialogFooter>
          <AlertDialogCancel ref={abort} disabled={deciding} onClick={() => onDecide("abort")}>
            Przerwij bez zapisu
          </AlertDialogCancel>
          <AlertDialogAction disabled={deciding} onClick={() => onDecide("continue")}>
            Kontynuuj
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
