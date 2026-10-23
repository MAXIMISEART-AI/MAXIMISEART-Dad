import * as React from "react"

import { getNotifications, markNotificationsRead, type Notifications } from "@/api/centrum"
import { useResource, type Resource } from "@/lib/use-resource"

type NotificationsValue = {
  notifications: Resource<Notifications>
  /** Tata zobaczył te Powiadomienia; odpowiedź serwera zastępuje listę, więc kropka na dzwonku gaśnie od razu. */
  markRead: (ids: ReadonlyArray<string>) => void
}

const NotificationsContext = React.createContext<NotificationsValue | null>(null)

/**
 * Powiadomienia wspólne dla dzwonka w nagłówku i widoku Powiadomienia. Karta czyta je przy starcie, po powrocie
 * do karty i przy każdej zmianie strony; serwer sam decyduje, kiedy zapytać Skrzynkę Zgłoszeń (najwyżej raz na
 * 10 minut). `page` to identyfikator bieżącej strony.
 */
export function NotificationsProvider({ page, children }: { page: string; children: React.ReactNode }) {
  const { resource, reload, replace } = useResource(getNotifications)
  const shownPage = React.useRef(page)

  React.useEffect(() => {
    if (shownPage.current !== page) {
      shownPage.current = page
      reload()
    }
  }, [page, reload])

  const markRead = React.useCallback(
    (ids: ReadonlyArray<string>) => {
      markNotificationsRead(ids).then((data) => replace({ state: "ready", data }), () => undefined)
    },
    [replace]
  )

  const value = React.useMemo(() => ({ notifications: resource, markRead }), [resource, markRead])

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

export function useNotifications(): NotificationsValue {
  const value = React.useContext(NotificationsContext)

  if (value === null) {
    throw new Error("useNotifications poza NotificationsProvider")
  }

  return value
}
