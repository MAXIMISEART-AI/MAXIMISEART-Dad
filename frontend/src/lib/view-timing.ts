import * as React from "react"

import { requestsBetween } from "@/api/client"
import { recordViewTiming } from "@/api/centrum"
import type { ViewTiming } from "@/api/generated"
import { zViewTiming } from "@/api/generated/zod.gen"
import type { Page } from "@/pages"

type ViewStart = { kind: ViewTiming["kind"]; at: number }

// Zimny start liczy się od początku ładowania karty, przejście w menu od zmiany adresu `#/<id>`.
let viewStart: ViewStart = { kind: "cold_start", at: 0 }

window.addEventListener("hashchange", () => {
  viewStart = { kind: "navigation", at: performance.now() }
})

// Gotowa treść: nagłówek bieżącej strony, a nigdzie szkieletu ani odczytu w toku.
const LOADING = "[data-slot=skeleton], [aria-busy=true]"

function isReady(page: Page): boolean {
  return document.querySelector("h1")?.textContent === page.title && document.querySelector(LOADING) === null
}

// Chromium podaje FCP dopiero po wyświetleniu klatki, czasem później niż gotowa treść.
const FCP_WAIT_MS = 2000

/** FCP karty w milisekundach od początku ładowania; `null`, gdy przeglądarka go nie poda. */
function firstContentfulPaint(): Promise<number | null> {
  return new Promise((resolve) => {
    const observer = new PerformanceObserver((entries) => {
      const paint = entries.getEntriesByName("first-contentful-paint")[0]

      if (paint !== undefined) {
        observer.disconnect()
        resolve(Math.round(paint.startTime))
      }
    })

    observer.observe({ type: "paint", buffered: true })
    setTimeout(() => {
      observer.disconnect()
      resolve(null)
    }, FCP_WAIT_MS)
  })
}

/**
 * Po cichu mierzy każdy gotowy widok (zimny start strony, przejście w menu) i wysyła pomiar do
 * dziennika Centrum: czas do gotowej treści, FCP przy zimnym starcie, czas szkieletu i zapytania API
 * z czasem serwera. Pomiar niczego nie pokazuje tacie; pomiar, którego kontrakt nie przyjmie, przepada.
 */
export function useViewTiming(page: Page) {
  React.useEffect(() => {
    const start = viewStart
    let skeletonSince: number | null = null
    let sent = false

    const measure = () => {
      const now = performance.now()

      if (skeletonSince === null && document.querySelector("[data-slot=skeleton]") !== null) {
        skeletonSince = now
      }

      if (sent || !isReady(page)) {
        return
      }

      sent = true
      observer.disconnect()

      const requests = requestsBetween(start.at, now)
      const fcp = start.kind === "cold_start" ? firstContentfulPaint() : Promise.resolve(null)

      void fcp.then((fcpMs) => {
        const timing = zViewTiming.safeParse({
          kind: start.kind,
          page: page.id,
          ready_ms: Math.round(now - start.at),
          fcp_ms: fcpMs,
          skeleton_ms: skeletonSince === null ? 0 : Math.round(now - skeletonSince),
          requests: requests.map(({ operation, browser_ms, server_ms }) => ({ operation, browser_ms, server_ms })),
        })

        if (timing.success && document.visibilityState === "visible") {
          recordViewTiming(timing.data)
        }
      })
    }

    const observer = new MutationObserver(measure)

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributeFilter: ["aria-busy", "data-slot"],
    })
    measure()

    return () => observer.disconnect()
  }, [page])
}
