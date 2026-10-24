import * as React from "react"
import { cn } from "cn"
import {
  CircleCheckIcon,
  ClockIcon,
  EyeIcon,
  LifeBuoyIcon,
  MessageSquareTextIcon,
  SendIcon,
  type LucideIcon,
} from "lucide-react"

import type { Notification } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useContentEntrance } from "@/lib/content-entrance"
import { ago } from "@/lib/format"
import { useNotifications } from "@/lib/notifications"

type Kind = Notification["kind"]

type CaseState = Notification["state"]

// Kolor rodzaju z palety motywu: niebieski Uwaga, pomarańczowy Zgłoszenie (zielony zostaje dla nowej wersji).
const KINDS: Record<Kind, { tag: string; color: string; icon: LucideIcon }> = {
  uwaga: { tag: "Uwaga", color: "var(--chart-1)", icon: MessageSquareTextIcon },
  zgloszenie: { tag: "Zgłoszenie", color: "var(--chart-2)", icon: LifeBuoyIcon },
}

// Uwaga jest rodzaju żeńskiego, Zgłoszenie nijakiego.
const STATES: Record<CaseState, { text: Record<Kind, string>; icon: LucideIcon; tone: string }> = {
  wyslana: {
    text: { uwaga: "Wysłana do Maksa.", zgloszenie: "Wysłane do Maksa." },
    icon: SendIcon,
    tone: "text-muted-foreground",
  },
  czeka_na_internet: {
    text: { uwaga: "Wyślę do Maksa, gdy będzie internet.", zgloszenie: "Wyślę do Maksa, gdy będzie internet." },
    icon: ClockIcon,
    tone: "text-muted-foreground",
  },
  rozwiazana: {
    text: { uwaga: "Rozwiązana. Będzie w następnej wersji.", zgloszenie: "Rozwiązane. Będzie w następnej wersji." },
    icon: CircleCheckIcon,
    tone: "text-success",
  },
  przeczytana: {
    text: { uwaga: "Maks przeczytał.", zgloszenie: "Maks przeczytał." },
    icon: EyeIcon,
    tone: "text-muted-foreground",
  },
}

/**
 * Widok Powiadomienia, otwierany dzwonkiem. Wejście oznacza wszystkie jako przeczytane, więc kropka na dzwonku
 * gaśnie od razu; wiersze, które były nowe, zachowują kropkę i jasne tło do wyjścia z widoku.
 */
export function NotificationsPage() {
  const { notifications, markRead } = useNotifications()
  const entrance = useContentEntrance(notifications.state === "loading")
  const data = notifications.state === "ready" ? notifications.data : null
  const unread = React.useMemo(() => data?.items.filter((item) => item.unread).map((item) => item.id) ?? [], [data])

  // Nowe w tej wizycie: każde Powiadomienie, które przyszło nieprzeczytane, zostaje oznaczone do wyjścia z widoku.
  const [visit, setVisit] = React.useState<{ unread: ReadonlyArray<string>; fresh: ReadonlySet<string> }>({
    unread: [],
    fresh: new Set(),
  })

  if (visit.unread !== unread) {
    setVisit({ unread, fresh: new Set([...visit.fresh, ...unread]) })
  }

  React.useEffect(() => {
    if (unread.length > 0) {
      markRead(unread)
    }
  }, [unread, markRead])

  const fresh = visit.fresh

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader title="Powiadomienia" />
      {notifications.state === "loading" ? <NotificationsSkeleton /> : null}
      {notifications.state === "failed" ? (
        <Alert variant="destructive" className="wejscie">
          <AlertTitle>Nie udało się odczytać Powiadomień</AlertTitle>
          <AlertDescription>{notifications.message}</AlertDescription>
        </Alert>
      ) : null}
      {data === null ? null : (
        <Card className={cn(entrance, "gap-0 p-0")} aria-label="Powiadomienia" role="list">
          {data.items.length === 0 ? (
            <p className="px-5 py-4 text-sm text-muted-foreground">
              Tu zobaczysz, co Maks zrobił z Twoimi Uwagami i Zgłoszeniami.
            </p>
          ) : (
            data.items.map((item) => <Row key={item.id} notification={item} fresh={fresh.has(item.id)} />)
          )}
        </Card>
      )}
    </div>
  )
}

function name(notification: Notification): string {
  return notification.kind === "uwaga" ? notification.title : notification.what
}

function Row({ notification, fresh }: { notification: Notification; fresh: boolean }) {
  const kind = KINDS[notification.kind]
  const state = STATES[notification.state]

  return (
    <article
      role="listitem"
      aria-label={`${kind.tag}: ${name(notification)}`}
      data-fresh={fresh}
      className="grid grid-cols-[auto_1fr_auto] items-start gap-x-4 border-t px-5 py-4 first:border-t-0 data-[fresh=true]:bg-muted/40"
    >
      <span
        className="flex size-9 items-center justify-center rounded-full [&_svg]:size-4"
        style={{ color: kind.color, backgroundColor: `color-mix(in oklab, ${kind.color} 12%, transparent)` }}
        aria-hidden
      >
        <kind.icon />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="text-sm font-medium text-pretty break-words">
          {name(notification)}
          {fresh ? (
            <span
              className="ml-2 inline-block size-1.5 rounded-full align-middle"
              style={{ backgroundColor: "var(--chart-1)" }}
              aria-label="nowe"
            />
          ) : null}
        </h2>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <state.icon className={`size-3.5 shrink-0 ${state.tone}`} aria-hidden />
          {state.text[notification.kind]}
        </p>
      </div>
      <div className="flex flex-col items-end gap-1.5 pt-0.5">
        <span className="inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap">
          <span className="size-1.5 rounded-full" style={{ backgroundColor: kind.color }} aria-hidden />
          {kind.tag}
        </span>
        <time className="text-xs whitespace-nowrap text-muted-foreground tabular-nums" dateTime={notification.at}>
          {ago(notification.at)}
        </time>
      </div>
    </article>
  )
}

function NotificationsSkeleton() {
  return (
    <Card className="gap-0 p-0" aria-busy="true">
      {[0, 1, 2].map((row) => (
        <div key={row} className="flex items-center gap-4 border-t px-5 py-4 first:border-t-0">
          <Skeleton className="size-9 rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3.5 w-1/3" />
          </div>
        </div>
      ))}
    </Card>
  )
}
