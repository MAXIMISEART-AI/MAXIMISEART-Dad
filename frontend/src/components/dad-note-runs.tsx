import { cn } from "cn"
import { EyeIcon } from "lucide-react"

import type { ProcessRun } from "@/api/centrum"
import { RunResultBadge } from "@/components/run-result-badge"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Skeleton } from "@/components/ui/skeleton"
import { dateTime } from "@/lib/format"
import type { Resource } from "@/lib/use-resource"

/** Uruchomienie z Centrum, do którego tata może przypiąć Uwagę: lista serwera ma tylko takie, z identyfikatorem. */
export type PinnableRun = ProcessRun & { run_id: string }

const MODE_WORDS: Record<ProcessRun["mode"], string> = { "DRY-RUN": "podgląd", RUN: "zapis" }

const SKELETON_ROWS = 3

const ROW = "flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0"

// Najwyżej cztery i pół wiersza: połowa wiersza mówi, że lista przewija się dalej. Na niskim ekranie lista oddaje
// wysokość aż do jednego wiersza, żeby „Wyślij” został na ekranie.
const LIST_HEIGHT = "max-h-63 min-h-14"

/** Lista ostatnich Uruchomień z Centrum do wyboru jednego, z wynikiem każdego; dane tylko z kontraktu. */
export function DadNoteRuns({
  runs,
  checked,
  onCheck,
}: {
  runs: Resource<ReadonlyArray<PinnableRun>>
  checked: string | null
  onCheck: (runId: string) => void
}) {
  switch (runs.state) {
    case "loading":
      return (
        <div aria-label="Wczytywanie Uruchomień" className="mt-1 overflow-hidden rounded-lg border">
          {Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <div key={row} className={ROW}>
              <Skeleton className="size-4 rounded-full" />
              <span className="flex flex-1 flex-col gap-1.5 py-0.5">
                <Skeleton className="h-3.5 w-40" />
                <Skeleton className="h-3 w-56" />
              </span>
            </div>
          ))}
        </div>
      )
    case "failed":
      return <p className="wejscie mt-1 text-sm text-muted-foreground">{runs.message}</p>
    case "ready":
      return runs.data.length === 0 ? (
        <p className="wejscie mt-1 rounded-lg border px-3 py-4 text-center text-sm text-muted-foreground">
          Nie ma jeszcze Uruchomień z Centrum.
        </p>
      ) : (
        <RadioGroup
          aria-label="Uruchomienie"
          value={checked}
          onValueChange={onCheck}
          ref={keepCheckedInView}
          className={cn("wejscie relative mt-1 content-start gap-0 overflow-y-auto overscroll-contain rounded-lg border", LIST_HEIGHT)}
        >
          {runs.data.map((run) => (
            <label key={run.run_id} className={cn(ROW, "cursor-pointer has-data-checked:bg-muted/60")}>
              <RadioGroupItem value={run.run_id} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-1.5 truncate">
                  {run.process_label}
                  {run.mode === "DRY-RUN" ? (
                    <EyeIcon className="size-3.5 text-muted-foreground" aria-label="podgląd" />
                  ) : null}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {run.period} · {MODE_WORDS[run.mode]} · {dateTime(run.started_at)}
                </span>
              </span>
              <RunResultBadge run={run} />
            </label>
          ))}
        </RadioGroup>
      )
    default: {
      const unhandled: never = runs

      return unhandled
    }
  }
}

/**
 * Trzyma zaznaczony wiersz w widoku listy od jej pojawienia się, także gdy lista maleje, bo „Maks dostanie” pod nią
 * urosło. Przewija tylko listę, nie okno, jak `scrollIntoView` z `block: "nearest"`, i bez animacji.
 */
function keepCheckedInView(list: HTMLElement | null) {
  if (list === null) {
    return
  }

  const observer = new ResizeObserver(() => {
    const row = list.querySelector("[data-checked]")?.closest("label")

    if (row) {
      const shown = Math.max(list.scrollTop, row.offsetTop + row.offsetHeight - list.clientHeight)

      list.scrollTop = Math.min(shown, row.offsetTop)
    }
  })

  observer.observe(list)

  return () => observer.disconnect()
}
