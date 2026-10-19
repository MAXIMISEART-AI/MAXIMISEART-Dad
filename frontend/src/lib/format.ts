// Prezentacja dat i czasów z kontraktu w zapisie taty. Bez arytmetyki dat: okresy i zakresy liczy serwer.

/** `2026-10-06` → `06.10.2026` */
export function fullDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")

  return `${day}.${month}.${year}`
}

/** `2026-10-06` → `06.10` */
export function shortDate(isoDate: string): string {
  return fullDate(isoDate).slice(0, 5)
}

const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
})

/** `2026-10-06T06:21:00Z` → `06.10.2026, 08:21` (czas komputera taty) */
export function dateTime(isoDateTime: string): string {
  return DATE_TIME.format(new Date(isoDateTime))
}

/** `2026-10-06T06:21:00Z` → `06.10` (dzień według czasu komputera taty) */
export function dayMonth(isoDateTime: string): string {
  return dateTime(isoDateTime).slice(0, 5)
}

const SECONDS = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** `10900` ms → `10,9 s` */
export function seconds(durationMs: number): string {
  // Zaokrąglenie na całych dziesiątych częściach sekundy, w górę od połowy (7250 ms → 7,3 s).
  return `${SECONDS.format(Math.round(durationMs / 100) / 10)} s`
}
