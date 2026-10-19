// Prezentacja dat z kontraktu (`2026-10-06`) w zapisie taty. Bez arytmetyki dat: okresy liczy serwer.

/** `2026-10-06` → `06.10.2026` */
export function fullDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")

  return `${day}.${month}.${year}`
}

/** `2026-10-06` → `06.10` */
export function shortDate(isoDate: string): string {
  return fullDate(isoDate).slice(0, 5)
}
