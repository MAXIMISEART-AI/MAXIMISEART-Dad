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

/**
 * Klasa wejścia (`className`) dla treści, która zmienia się na oczach taty: od pierwszej zmiany `value`
 * po montowaniu. Stan zastany przy wejściu na stronę stoi w miejscu. Treść, która ma wejść, nosi `key`
 * od `value`, bo przejście z `@starting-style` gra tylko przy wstawieniu elementu.
 */
export function useChangeEntrance<T>(value: T, className: string): string | undefined {
  const [atMount] = React.useState(value)
  const [changed, setChanged] = React.useState(false)

  if (!changed && value !== atMount) {
    setChanged(true)
  }

  return changed ? className : undefined
}
