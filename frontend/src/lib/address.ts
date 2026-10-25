import * as React from "react"

import type { ViewTiming } from "@/api/generated"

type PageId = ViewTiming["page"]

/** Adres strony Centrum: `#/<id>`, a za nim człony strony, np. `#/uzupelnienie/<okres>`. */
export type Href = `#/${PageId}` | `#/${PageId}/${string}`

/** Adres strony `id` z członami `path` (np. tokenem okresu); każdy człon jest kodowany osobno. */
export function href(id: PageId, ...path: ReadonlyArray<string>): Href {
  return path.length === 0 ? `#/${id}` : `#/${id}/${path.map(encodeURIComponent).join("/")}`
}

function decoded(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    // Adres wpisany ręcznie z pojedynczym `%`: strona dostaje człon taki, jaki jest, a serwer go odrzuci.
    return part
  }
}

/** `#/uzupelnienie/06_12_10_2026` → `["uzupelnienie", "06_12_10_2026"]` */
export function hashParts(hash: string): ReadonlyArray<string> {
  return hash.replace(/^#\/?/, "").split("/").map(decoded)
}

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange)

  return () => window.removeEventListener("hashchange", onChange)
}

/** Bieżący adres karty (`location.hash`); zmienia się z każdym przejściem, także Wstecz w przeglądarce. */
export function useHash(): string {
  return React.useSyncExternalStore(subscribe, () => window.location.hash)
}

/** Człony adresu za identyfikatorem strony: `#/uzupelnienie/06_12_10_2026` → `["06_12_10_2026"]`. */
export function usePagePath(): ReadonlyArray<string> {
  const hash = useHash()

  return React.useMemo(() => hashParts(hash).slice(1), [hash])
}
