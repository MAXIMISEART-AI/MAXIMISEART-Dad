import * as React from "react"
import { CircleArrowUpIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react"

import type { Configuration } from "@/api/centrum"
import { ToolUpdateButton, ToolUpdateStatus } from "@/components/tool-update"
import { Badge } from "@/components/ui/badge"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToolUpdate } from "@/lib/tool-update"

type Freshness = Configuration["freshness"]

const FRESHNESS: Record<Freshness, { label: string; icon: React.ReactNode }> = {
  current: { label: "Aktualna", icon: <CircleCheckIcon data-icon="inline-start" className="text-success" /> },
  newer: { label: "Jest nowsza wersja", icon: <CircleArrowUpIcon data-icon="inline-start" className="text-warning" /> },
  not_checked: {
    label: "Nie sprawdzono",
    icon: <CircleDashedIcon data-icon="inline-start" className="text-muted-foreground" />,
  },
}

/**
 * Wersja narzędzia z Aktualnością i przyciskiem `Zaktualizuj narzędzie`. Po aktualizacji strona czyta
 * Konfigurację od nowa (`onFinished`), więc commit i Aktualność pochodzą z serwera, nie z wyniku. Udana
 * aktualizacja kończy się ponownym startem Centrum i przeładowaniem karty: nową wersję widać w commicie. Po
 * porażce głównym przyciskiem jest to, co każe Komunikat: ponowna aktualizacja albo „Wyślij do Maksa”.
 */
export function ToolCard({
  version,
  commit,
  freshness,
  onFinished,
}: {
  version: string
  commit: string | null
  freshness: Freshness
  onFinished: () => void
}) {
  const { update } = useToolUpdate()
  const watched = React.useRef(false)

  React.useEffect(() => {
    if (update?.state === "running") {
      watched.current = true
    } else if (watched.current) {
      watched.current = false
      onFinished()
    }
  }, [update, onFinished])

  return (
    <Card role="region" aria-labelledby="narzedzie" className="@4xl/main:col-span-2">
      <CardHeader>
        <CardTitle id="narzedzie">Narzędzie</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
          <span>Wersja {version}</span>
          {commit === null ? null : (
            <>
              <span aria-hidden>·</span>
              <span className="font-mono text-xs" aria-label="Commit">
                {commit}
              </span>
            </>
          )}
          <Badge variant="outline" className="ml-1">
            {FRESHNESS[freshness].icon}
            {FRESHNESS[freshness].label}
          </Badge>
        </CardDescription>
        <CardAction>
          <ToolUpdateButton primary={freshness === "newer"} />
        </CardAction>
      </CardHeader>
      {/* Bez stanu aktualizacji (np. przed kliknięciem) karta nie ma treści pod nagłówkiem. */}
      <CardContent className="empty:hidden">
        <ToolUpdateStatus />
      </CardContent>
    </Card>
  )
}
