import type * as React from "react"
import { FileSpreadsheetIcon, FileTextIcon, FolderOpenIcon, UsersIcon } from "lucide-react"

import type { OpenTarget, PeriodRow } from "@/api/centrum"
import { PeriodStatusBadge } from "@/components/period-status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { shortDate } from "@/lib/format"
import { openAndConfirm } from "@/pages/periods/open-period-path"

/** Tablica okresów: od najnowszego, ostatni pełny okres wyróżniony tłem. */
export function PeriodBoardTable({
  periods,
  onStale,
}: {
  periods: ReadonlyArray<PeriodRow>
  onStale: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle id="tablica-okresow">Tablica okresów</CardTitle>
      </CardHeader>
      <CardContent>
        <Table aria-labelledby="tablica-okresow">
          <TableHeader>
            <TableRow>
              <TableHead>Okres</TableHead>
              <TableHead>Status okresu</TableHead>
              <TableHead>Pliki</TableHead>
              <TableHead className="text-right">Następny krok</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {periods.map((period) => (
              <PeriodBoardRow key={period.token} period={period} onStale={onStale} />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function PeriodBoardRow({ period, onStale }: { period: PeriodRow; onStale: () => void }) {
  return (
    <TableRow data-state={period.last_complete ? "selected" : undefined}>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-medium tabular-nums">{period.token}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {shortDate(period.tuesday)} – {shortDate(period.monday)}
            {period.last_complete ? <span className="sr-only">, ostatni pełny okres</span> : null}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <PeriodStatusBadge period={period} />
      </TableCell>
      <TableCell>
        <PeriodFiles period={period} onStale={onStale} />
      </TableCell>
      <TableCell className="text-right">
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="rounded-md text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 data-[closed=true]:text-muted-foreground data-[closed=false]:font-medium"
                data-closed={period.next_step.action === "none"}
              />
            }
          >
            {period.next_step.action === "none" ? "Zamknięty" : period.next_step.label}
          </TooltipTrigger>
          <TooltipContent>{period.next_step.hint}</TooltipContent>
        </Tooltip>
      </TableCell>
    </TableRow>
  )
}

function PeriodFiles({ period, onStale }: { period: PeriodRow; onStale: () => void }) {
  const open = (target: OpenTarget) => openAndConfirm(period.token, target, onStale)

  return (
    <div className="flex items-center gap-0.5">
      <FileButton
        label="Rozliczenie wewnętrzne"
        token={period.token}
        icon={<FileTextIcon />}
        exists={period.internal_settlement_exists}
        onOpen={() => open("internal_settlement")}
      />
      <FileButton
        label="Plik zbiorczy"
        token={period.token}
        icon={<FileSpreadsheetIcon />}
        exists={period.collective_file_exists}
        onOpen={() => open("collective_file")}
      />
      <FileButton
        label="Folder okresu"
        token={period.token}
        icon={<FolderOpenIcon />}
        exists={period.period_folder_exists}
        onOpen={() => open("period_folder")}
      />
      <FileButton
        label="Rozliczenia pracowników"
        token={period.token}
        icon={<UsersIcon data-icon="inline-start" />}
        exists={period.worker_settlements_folder_exists}
        count={period.worker_settlements_folder_exists ? period.worker_settlement_count : undefined}
        onOpen={() => open("worker_settlements_folder")}
      />
    </div>
  )
}

function FileButton({
  label,
  token,
  icon,
  exists,
  count,
  onOpen,
}: {
  label: string
  token: string
  icon: React.ReactNode
  exists: boolean
  count?: number
  onOpen: () => void
}) {
  const description = count === undefined ? label : `${label}: ${count}`

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size={count === undefined ? "icon-sm" : "sm"}
            disabled={!exists}
            aria-label={`${description}, okres ${token}`}
            onClick={onOpen}
          />
        }
      >
        {icon}
        {count === undefined ? null : <span className="tabular-nums">{count}</span>}
      </TooltipTrigger>
      <TooltipContent>{exists ? description : `${label}: jeszcze nie ma`}</TooltipContent>
    </Tooltip>
  )
}
