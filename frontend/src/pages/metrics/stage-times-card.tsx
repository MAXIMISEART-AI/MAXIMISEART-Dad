import { Bar, BarChart, CartesianGrid, XAxis, YAxis, type TooltipValueType } from "recharts"
import { TimerOffIcon } from "lucide-react"

import type { Percentiles, ProcessRun } from "@/api/centrum"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { dateTime, dayMonth, seconds } from "@/lib/format"
import { measuredPhases, phaseDuration } from "@/pages/metrics/process-runs"

// Ostatnie Uruchomienia procesu na wykresie; starsze są w historii.
const CHART_RUNS = 12

// Cztery sloty palety wykresu sprawdzone w prototypie (#95), po jednym na etap.
const PHASE_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"]

type ChartRow = {
  key: string
  label: string
  run: ProcessRun
} & Record<`phase${number}`, number>

/** Czasy etapów kolejnych Uruchomień procesu wybranego procesu i trybu: wykres albo tabela z P50/P95. */
export function StageTimesCard({
  phases,
  runs,
  percentiles,
}: {
  phases: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
  percentiles: Percentiles | undefined
}) {
  const recent = runs.slice(0, CHART_RUNS).toReversed()
  const shown = measuredPhases(phases, recent)
  // Klucz serii to numer etapu: nazwy etapów mają spacje, a z klucza powstaje zmienna CSS koloru.
  const keyOf = (phase: string) => `phase${phases.indexOf(phase)}`

  const config: ChartConfig = Object.fromEntries(
    phases.map((phase, index) => [keyOf(phase), { label: phase, color: PHASE_COLORS[index] }])
  )

  const rows: ChartRow[] = recent.map((run) => ({
    key: run.started_at,
    label: `${dayMonth(run.started_at)}${run.result === "BLAD_KRYTYCZNY" ? " ✕" : ""}`,
    run,
    ...Object.fromEntries(shown.map((phase) => [keyOf(phase), phaseDuration(run, phase)])),
  }))

  return (
    <Card>
      <Tabs defaultValue="wykres" className="gap-4">
        <CardHeader>
          <CardTitle id="czasy-etapow">Czasy etapów</CardTitle>
          <CardAction>
            <TabsList>
              <TabsTrigger value="wykres">Wykres</TabsTrigger>
              <TabsTrigger value="tabela">Tabela</TabsTrigger>
            </TabsList>
          </CardAction>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <TimerOffIcon />
                </EmptyMedia>
                <EmptyTitle>Ten proces nie był jeszcze uruchomiony w tym trybie</EmptyTitle>
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              <TabsContent value="wykres">
                <figure aria-label="Wykres czasów etapów">
                  <ChartContainer config={config} className="aspect-auto h-72 w-full">
                    <BarChart data={rows} margin={{ left: 0, right: 8, top: 8 }} accessibilityLayer>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} />
                      <YAxis tickLine={false} axisLine={false} width={56} tickFormatter={seconds} />
                      <ChartTooltip
                        cursor={false}
                        content={
                          <ChartTooltipContent
                            labelFormatter={(_, payload) => {
                              const row = rows.find((candidate) => candidate.key === payload[0]?.payload?.key)

                              return row === undefined ? null : tooltipTitle(row.run)
                            }}
                            formatter={phaseTime(config)}
                          />
                        }
                      />
                      <ChartLegend content={<ChartLegendContent />} />
                      {shown.map((phase, index) => (
                        <Bar
                          key={phase}
                          dataKey={keyOf(phase)}
                          stackId="etapy"
                          fill={`var(--color-${keyOf(phase)})`}
                          stroke="var(--card)"
                          strokeWidth={2}
                          maxBarSize={28}
                          radius={index === shown.length - 1 ? [4, 4, 0, 0] : 0}
                          // Przełączenie filtra nie animuje słupków.
                          isAnimationActive={false}
                        />
                      ))}
                    </BarChart>
                  </ChartContainer>
                </figure>
              </TabsContent>
              <TabsContent value="tabela">
                <StageTimesTable phases={shown} runs={recent.toReversed()} percentiles={percentiles} />
              </TabsContent>
            </>
          )}
        </CardContent>
      </Tabs>
    </Card>
  )
}

/** Wiersz podpowiedzi wykresu: nazwa etapu i jego czas. */
function phaseTime(config: ChartConfig) {
  return (value: TooltipValueType | undefined, name: number | string | undefined) => (
    <div className="flex w-full justify-between gap-4">
      <span className="text-muted-foreground">{config[String(name)]?.label}</span>
      <span className="font-medium tabular-nums">{seconds(Number(value))}</span>
    </div>
  )
}

function tooltipTitle(run: ProcessRun): string {
  const stopped = run.result === "BLAD_KRYTYCZNY" ? " · zatrzymano" : ""

  return `${dateTime(run.started_at)} · okres ${run.period}${stopped}`
}

function StageTimesTable({
  phases,
  runs,
  percentiles,
}: {
  phases: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
  percentiles: Percentiles | undefined
}) {
  const phaseRange = (phase: string) => percentiles?.phases.find((entry) => entry.phase === phase)

  return (
    <Table aria-labelledby="czasy-etapow">
      <TableHeader>
        <TableRow>
          <TableHead>Data</TableHead>
          <TableHead>Okres</TableHead>
          {phases.map((phase) => (
            <TableHead key={phase} className="text-right">
              {phase}
            </TableHead>
          ))}
          <TableHead className="text-right">Całość</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.started_at}>
            <TableCell className="tabular-nums">
              {dateTime(run.started_at)}
              {run.result === "BLAD_KRYTYCZNY" ? <span className="text-destructive"> ✕ zatrzymano</span> : null}
            </TableCell>
            <TableCell className="tabular-nums">{run.period}</TableCell>
            {phases.map((phase) => (
              <TableCell key={phase} className="text-right tabular-nums">
                {phaseDuration(run, phase) > 0 ? seconds(phaseDuration(run, phase)) : "–"}
              </TableCell>
            ))}
            <TableCell className="text-right tabular-nums">{seconds(run.total_duration_ms)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
      {percentiles === undefined ? null : (
        <TableFooter>
          {(["p50_ms", "p95_ms"] as const).map((key) => (
            <TableRow key={key}>
              <TableCell colSpan={2} className="font-medium">
                {key === "p50_ms" ? "P50" : "P95"}
              </TableCell>
              {phases.map((phase) => {
                const range = phaseRange(phase)

                return (
                  <TableCell key={phase} className="text-right tabular-nums">
                    {range === undefined ? "–" : seconds(range[key])}
                  </TableCell>
                )
              })}
              <TableCell className="text-right tabular-nums">{seconds(percentiles[key])}</TableCell>
            </TableRow>
          ))}
        </TableFooter>
      )}
    </Table>
  )
}
