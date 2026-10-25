import { cn } from "cn"
import { ArrowLeftIcon, CalendarRangeIcon, ChevronRightIcon, CircleCheckIcon, CircleDashedIcon, FileSpreadsheetIcon } from "lucide-react"

import {
  getQuantitiesToFill,
  type DescriptionColumn,
  type FillKind,
  type KindToFill,
  type QuantitiesToFill,
} from "@/api/centrum"
import { zFillKind } from "@/api/generated/zod.gen"
import { PageHeader } from "@/components/page-header"
import { ThreePartMessage } from "@/components/three-part-message"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { href, usePagePath } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { KindPage } from "@/pages/filling/kind-page"
import { openAndConfirm } from "@/pages/periods/open-period-path"

const TITLE = "Uzupełnienie pliku zbiorczego"

const KINDS: Record<FillKind, { title: string; hint: string }> = {
  without_rule: { title: "Wiersze bez reguły", hint: "Dopisz ilości poza V, T i N." },
  from_description: { title: "Wiersze z opisu", hint: "Wpisz ilości według opisu technika." },
}

// `useResource` pamięta ostatnie dane pod funkcją odczytu, więc każdy okres ma jedną, tę samą funkcję.
const loads = new Map<string, () => Promise<QuantitiesToFill>>()

function quantitiesOf(token: string) {
  let load = loads.get(token)

  if (load === undefined) {
    load = () => getQuantitiesToFill(token)
    loads.set(token, load)
  }

  return load
}

/** Podsumowanie Uzupełnienia pliku zbiorczego okresu z adresu `#/uzupelnienie/<okres>`. */
export function FillingPage() {
  const [token = "", part] = usePagePath()
  const { filesVersion } = useSettings()
  const kind = zFillKind.safeParse(part)

  if (kind.success) {
    return (
      <KindPage
        key={`${token}/${kind.data}/${filesVersion}`}
        title={TITLE}
        token={token}
        kind={kind.data}
        heading={KINDS[kind.data].title}
        hint={KINDS[kind.data].hint}
        action={<OpenCollectiveFile token={token} />}
      />
    )
  }

  return (
    <>
      <a
        href={href("okresy")}
        className="-mb-4 flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeftIcon className="size-4" aria-hidden />
        Okresy
      </a>
      <PageHeader
        title={TITLE}
        badge={
          <Badge variant="outline" className="tabular-nums">
            <CalendarRangeIcon aria-hidden />
            {token}
          </Badge>
        }
        action={<OpenCollectiveFile token={token} />}
      />
      {/* Inny okres albo nowe pliki taty to nowy odczyt; zmiana motywu nim nie jest. */}
      <FillingContent key={`${token}/${filesVersion}`} token={token} />
    </>
  )
}

function OpenCollectiveFile({ token }: { token: string }) {
  return (
    <Button size="lg" onClick={() => openAndConfirm(token, { target: "collective_file" })}>
      <FileSpreadsheetIcon data-icon="inline-start" />
      Otwórz Plik zbiorczy
    </Button>
  )
}

function FillingContent({ token }: { token: string }) {
  const { resource } = useResource(quantitiesOf(token))
  const entrance = useContentEntrance(resource.state === "loading")

  switch (resource.state) {
    case "loading":
      return <FillingSkeleton />
    case "failed":
      return (
        <Alert variant="destructive" className="wejscie">
          <AlertTitle>Nie udało się odczytać okresu</AlertTitle>
          <AlertDescription>{resource.message}</AlertDescription>
        </Alert>
      )
    case "ready": {
      const found = resource.data

      return found.state === "problem" ? (
        <div className={entrance}>
          <ThreePartMessage message={found.message} kind="notice" />
        </div>
      ) : (
        <div className={cn(entrance, "flex flex-col gap-3")}>
          <Card className="py-0">
            <CardContent className="divide-y px-0">
              {found.kinds.map((kind) => (
                <KindSection key={kind.kind} token={token} kind={kind} />
              ))}
              <DescriptionColumns columns={found.description_columns} />
            </CardContent>
          </Card>
          <p className="px-1 text-sm text-muted-foreground">Nie widzisz zmian? Zapisz w Excelu (Ctrl+S).</p>
        </div>
      )
    }

    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}

/** Rodzaj z listą: licznik „x z y” i numery wierszy; zrobiony rodzaj (także bez wierszy) jest spokojnie odhaczony. */
function KindSection({ token, kind }: { token: string; kind: KindToFill }) {
  const { title, hint } = KINDS[kind.kind]
  const doneRows = kind.rows.filter((row) => row.done).length

  return (
    <section aria-label={title} className="flex gap-3 px-6 py-5">
      {kind.done ? (
        <CircleCheckIcon className="mt-0.5 size-5 shrink-0 text-success" aria-label="Zrobione" />
      ) : (
        <CircleDashedIcon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="Do uzupełnienia" />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {/* Rodzaj z wierszami prowadzi do swojej tabeli; bez wierszy nie ma czego otwierać. */}
        <a
          href={kind.rows.length === 0 ? undefined : href("uzupelnienie", token, kind.kind)}
          className="-mx-2 -my-1 flex items-center gap-3 rounded-md px-2 py-1 transition-[background-color,scale] duration-150 ease-out [&[href]]:active:scale-[0.99] [&[href]]:active:bg-muted"
        >
          <div className="flex flex-col gap-0.5">
            <h2 className="font-medium">{title}</h2>
            <p className="text-sm text-muted-foreground">
              {kind.rows.length === 0 ? "Nie ma takich wierszy." : hint}
            </p>
          </div>
          {kind.rows.length === 0 ? null : (
            <>
              <span className="ml-auto text-sm font-medium tabular-nums">
                {doneRows} z {kind.rows.length}
              </span>
              <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            </>
          )}
        </a>
        {kind.rows.length === 0 ? null : (
          <ul aria-label={`Numery wierszy: ${title}`} className="flex flex-wrap gap-1.5">
            {kind.rows.map(({ row, done }) => (
              <li
                key={row}
                className={cn(
                  "rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums",
                  done ? "text-muted-foreground line-through decoration-muted-foreground/50" : "bg-secondary"
                )}
              >
                {row}
                {done ? <span className="sr-only"> zrobiony</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

/** „w 1 wierszu”, „w 3 wierszach”, „w 12 wierszach” */
function inRows(rows: number): string {
  return `w ${rows} ${rows === 1 ? "wierszu" : "wierszach"}`
}

/** Przypomnienie o kolumnach z opisu technika: bez stanu „zrobione”, tylko w ilu wierszach coś wpisano. */
function DescriptionColumns({ columns }: { columns: ReadonlyArray<DescriptionColumn> }) {
  return (
    <section aria-label="Kolumny z opisu technika" className="flex flex-col gap-3 px-6 py-5 pl-14">
      <div className="flex flex-col gap-0.5">
        <h2 className="font-medium">Kolumny z opisu technika</h2>
        <p className="text-sm text-muted-foreground">W każdym wierszu według CZYNNOŚCI ZREALIZOWANE.</p>
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {columns.map(({ column, rows }) => (
          <div key={column} className="flex flex-col gap-0.5 rounded-md bg-muted/50 px-2.5 py-2">
            <dt className="font-mono text-sm font-medium">{column}</dt>
            <dd className="text-xs text-muted-foreground">{rows === 0 ? "nic nie wpisano" : `wpisane ${inRows(rows)}`}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function FillingSkeleton() {
  return (
    <Card aria-busy="true" aria-label="Wczytywanie Ilości do uzupełnienia">
      <CardContent className="flex flex-col gap-5 py-2">
        {[0, 1].map((kind) => (
          <div key={kind} className="flex flex-col gap-3">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-6 w-80" />
          </div>
        ))}
        <Skeleton className="h-14 w-full" />
      </CardContent>
    </Card>
  )
}
