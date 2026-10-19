import * as React from "react"
import { CalendarRangeIcon, PlayIcon, type LucideIcon } from "lucide-react"

import { PeriodsPage } from "@/pages/periods/periods-page"
import { RunsPage } from "@/pages/runs/runs-page"

/**
 * Strony z bocznego menu. Nowa strona to nowy wpis: menu, adres `#/<id>` i treść biorą się stąd.
 * Kolejność wpisów to kolejność w menu; pierwszy wpis jest stroną startową.
 */
export const PAGES = [
  { id: "okresy", title: "Okresy", icon: CalendarRangeIcon, Content: PeriodsPage },
  { id: "uruchomienia", title: "Uruchomienia", icon: PlayIcon, Content: RunsPage },
] as const satisfies ReadonlyArray<{
  id: string
  title: string
  icon: LucideIcon
  Content: React.ComponentType
}>

export type Page = (typeof PAGES)[number]

function pageFromHash(): Page {
  const id = window.location.hash.replace(/^#\//, "")

  return PAGES.find((page) => page.id === id) ?? PAGES[0]
}

export function pageHref(page: Page): string {
  return `#/${page.id}`
}

/** Bieżąca strona z adresu (`#/okresy`), więc działa Wstecz w przeglądarce i odświeżenie karty. */
export function useCurrentPage(): Page {
  return React.useSyncExternalStore(
    (onChange) => {
      window.addEventListener("hashchange", onChange)

      return () => window.removeEventListener("hashchange", onChange)
    },
    pageFromHash
  )
}
