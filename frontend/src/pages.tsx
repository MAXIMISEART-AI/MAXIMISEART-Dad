import * as React from "react"
import { BellIcon, CalendarRangeIcon, ChartColumnIcon, PlayIcon, SlidersHorizontalIcon, type LucideIcon } from "lucide-react"

import type { ViewTiming } from "@/api/generated"
import { ConfigurationPage } from "@/pages/configuration/configuration-page"
import { MetricsPage } from "@/pages/metrics/metrics-page"
import { NotificationsPage } from "@/pages/notifications/notifications-page"
import { PeriodsPage } from "@/pages/periods/periods-page"
import { RunsPage } from "@/pages/runs/runs-page"

// Widok Powiadomienia, do którego prowadzi dzwonek w nagłówku; bez pozycji w menu.
export const NOTIFICATIONS_PAGE = {
  id: "powiadomienia",
  title: "Powiadomienia",
  icon: BellIcon,
  Content: NotificationsPage,
  menu: false,
} as const

/**
 * Strony Centrum. Nowa strona to nowy wpis: menu, adres `#/<id>` i treść biorą się stąd. Strona z `menu: false`
 * (Powiadomienia, otwierane dzwonkiem) nie ma pozycji w menu. Kolejność wpisów to kolejność w menu; pierwszy wpis
 * jest stroną startową.
 */
export const PAGES = [
  { id: "okresy", title: "Okresy", icon: CalendarRangeIcon, Content: PeriodsPage, menu: true },
  { id: "uruchomienia", title: "Uruchomienia", icon: PlayIcon, Content: RunsPage, menu: true },
  { id: "metryki", title: "Metryki", icon: ChartColumnIcon, Content: MetricsPage, menu: true },
  { id: "konfiguracja", title: "Konfiguracja", icon: SlidersHorizontalIcon, Content: ConfigurationPage, menu: true },
  NOTIFICATIONS_PAGE,
] as const satisfies ReadonlyArray<{
  // Identyfikator strony z kontraktu: pod nim pomiar widoku trafia do dziennika Centrum.
  id: ViewTiming["page"]
  title: string
  icon: LucideIcon
  Content: React.ComponentType
  menu: boolean
}>

export type Page = (typeof PAGES)[number]

export type PageHref = `#/${Page["id"]}`

function pageFromHash(): Page {
  const id = window.location.hash.replace(/^#\//, "")

  return PAGES.find((page) => page.id === id) ?? PAGES[0]
}

export function pageHref(page: Page): PageHref {
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
