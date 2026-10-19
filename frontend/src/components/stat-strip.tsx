import type * as React from "react"

import { Card } from "@/components/ui/card"

export type Stat = {
  label: string
  icon: React.ReactNode
  value: React.ReactNode
  note?: React.ReactNode
}

/** Kilka najważniejszych liczb w jednej karcie, rozdzielonych liniami; bez efektu hover, bo to nie przycisk. */
export function StatStrip({ stats, label }: { stats: ReadonlyArray<Stat>; label: string }) {
  return (
    <Card
      role="group"
      aria-label={label}
      className="grid auto-cols-fr grid-flow-col divide-x py-0"
    >
      {stats.map((stat) => (
        <div key={stat.label} className="flex min-w-0 flex-col gap-1 p-5" role="group" aria-label={stat.label}>
          <span className="flex items-center gap-2 text-sm text-muted-foreground [&_svg]:size-4">
            {stat.icon}
            {stat.label}
          </span>
          <span className="text-2xl font-semibold tabular-nums">{stat.value}</span>
          {stat.note === undefined ? null : (
            <span className="text-sm text-muted-foreground tabular-nums">{stat.note}</span>
          )}
        </div>
      ))}
    </Card>
  )
}
