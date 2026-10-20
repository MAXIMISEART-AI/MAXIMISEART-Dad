import { cn } from "cn"
import { FolderSearchIcon, FolderXIcon } from "lucide-react"

import { getPeriodBoard, type PeriodBoard } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useAppearance } from "@/lib/appearance"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { FileSettingsCard } from "@/pages/periods/file-settings-card"
import { NextStepCard } from "@/pages/periods/next-step-card"
import { PeriodBoardTable } from "@/pages/periods/period-board-table"
import { PeriodStats } from "@/pages/periods/period-stats"
import { RepairNotice } from "@/pages/periods/repair-notice"

export function PeriodsPage() {
  const { settings } = useSettings()
  const appearance = useAppearance(settings.state === "loading")

  return (
    <>
      <PageHeader title="Okresy" />
      <RepairNotice />
      {settings.state === "loading" ? <PeriodsSkeleton /> : null}
      {settings.state === "failed" ? <Failure message={settings.message} /> : null}
      {settings.state === "ready" ? (
        <div className={cn(appearance, "flex flex-col gap-6")}>
          {/* Nowy folder okresów to nowy odczyt Tablicy okresów. */}
          <PeriodBoardSection key={JSON.stringify(settings.data.periods_directory)} />
          <FileSettingsCard settings={settings.data} />
        </div>
      ) : null}
    </>
  )
}

function PeriodBoardSection() {
  const { resource: board, reload } = useResource(getPeriodBoard)

  switch (board.state) {
    case "loading":
      return <PeriodsSkeleton />
    case "failed":
      return <Failure message={board.message} />
    case "ready":
      return <BoardContent board={board.data} reload={reload} />
    default: {
      const unhandled: never = board

      return unhandled
    }
  }
}

function BoardContent({ board, reload }: { board: PeriodBoard; reload: () => void }) {
  const { choosePeriodsDirectory } = useSettings()

  switch (board.state) {
    case "not_set":
      return (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderSearchIcon />
            </EmptyMedia>
            <EmptyTitle>Wskaż folder okresów</EmptyTitle>
            <EmptyDescription>Centrum znajdzie w nim Foldery okresu.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={choosePeriodsDirectory}>Wskaż folder okresów</Button>
          </EmptyContent>
        </Empty>
      )
    case "missing":
      return (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderXIcon />
            </EmptyMedia>
            <EmptyTitle>Nie ma folderu okresów {board.name}</EmptyTitle>
            <EmptyDescription>Mógł zostać przeniesiony albo przemianowany.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={choosePeriodsDirectory}>Wskaż folder okresów</Button>
          </EmptyContent>
        </Empty>
      )
    case "ready": {
      const lastComplete = board.periods.find((period) => period.last_complete)

      return (
        <>
          {lastComplete === undefined ? null : <NextStepCard period={lastComplete} />}
          <PeriodStats periods={board.periods} lastPrepared={board.last_prepared_period} />
          <PeriodBoardTable periods={board.periods} onStale={reload} />
        </>
      )
    }

    default: {
      const unhandled: never = board

      return unhandled
    }
  }
}

function Failure({ message }: { message: string }) {
  return (
    <Alert variant="destructive" className="wejscie">
      <AlertTitle>Nie udało się odczytać okresów</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}

function PeriodsSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Wczytywanie okresów">
      <Card>
        <CardContent className="flex flex-col gap-4 py-2">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-9 w-96" />
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-6 w-[30rem]" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-36" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {[0, 1, 2, 3, 4].map((row) => (
            <Skeleton key={row} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
