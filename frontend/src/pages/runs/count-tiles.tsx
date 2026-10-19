import { TriangleAlertIcon } from "lucide-react"

import type { Count } from "@/api/centrum"

/** Liczby z etykietami jako kafelki (np. Zlecenia na dzień); zero ma ikonę, nie tylko kolor. */
export function CountTiles({ title, counts }: { title: string; counts: ReadonlyArray<Count> }) {
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <h3 className="text-sm font-medium">{title}</h3>
      <ul className="grid grid-cols-7 gap-2">
        {counts.map((count) => (
          <li
            key={count.label}
            aria-label={`${count.label}: ${count.count}`}
            data-zero={count.count === 0}
            className="flex flex-col items-center gap-1 rounded-lg bg-muted/60 px-1 py-2 data-[zero=true]:bg-warning/10"
          >
            <span className="text-xs text-muted-foreground tabular-nums">{count.label}</span>
            <span className="flex items-center gap-1 text-lg font-semibold tabular-nums">
              {count.count === 0 ? <TriangleAlertIcon className="size-3.5 text-warning" aria-hidden /> : null}
              {count.count}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Pasek kilku liczb w jednej karcie z separatorami. */
export function NumberStrip({ numbers }: { numbers: ReadonlyArray<readonly [string, number]> }) {
  return (
    <dl className="grid grid-cols-3 divide-x rounded-lg border">
      {numbers.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-1 px-4 py-3">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}
