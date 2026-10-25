import { EyeIcon } from "lucide-react"

import type { RowState } from "@/api/generated"

/** Po Przebiegu rozliczeń okresu strony Uzupełnienia są podglądem tego, co tata uzupełnił. */
export function AfterSettlement() {
  return (
    <p role="status" className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
      <EyeIcon className="size-4 shrink-0" aria-hidden />
      Przebieg rozliczeń się odbył · tylko podgląd
    </p>
  )
}

/** Podpowiedź rodzaju po Przebiegu: zamiast „co wpisać” to, co zostało na zerach. */
export function afterSettlementHint(rows: ReadonlyArray<{ state: RowState }>): string {
  return rows.some((row) => row.state === "without_quantity") ? "Szare zostały bez ilości." : "Każdy wiersz uzupełniony."
}
