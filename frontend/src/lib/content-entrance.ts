import * as React from "react"

/**
 * Klasa wejścia treści po szkielecie (`pojawienie`), gdy przy montowaniu trwał odczyt. Treść gotowa od
 * pierwszego renderu (ostatnie dane strony, na której tata już był) pokazuje się od razu, bez przejścia:
 * po menu tata klika wiele razy dziennie.
 */
export function useContentEntrance(loading: boolean): string | undefined {
  const [afterLoading] = React.useState(loading)

  return afterLoading ? "pojawienie" : undefined
}
