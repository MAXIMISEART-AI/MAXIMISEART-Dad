import type * as React from "react"

import { ToolUpdateAfterRestart } from "@/components/tool-update"

// Duży tytuł strony, obok najwyżej jedna odznaka, po prawej najwyżej jedna akcja. Bez akapitu pod spodem; tylko po
// ponownym starcie zakończonym porażką pod tytułem każdej strony jest Komunikat Aktualizacji narzędzia.
export function PageHeader({
  title,
  badge,
  action,
}: {
  title: string
  badge?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <>
      <div className="flex min-h-10 items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {badge}
        {action === undefined ? null : <div className="ml-auto flex items-center gap-2">{action}</div>}
      </div>
      <ToolUpdateAfterRestart />
    </>
  )
}
