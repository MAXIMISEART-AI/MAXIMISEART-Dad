import * as React from "react"
import { FileSpreadsheetIcon, FolderIcon, TriangleAlertIcon } from "lucide-react"

import type { PathSetting, Settings } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useSettings } from "@/lib/settings"

/** Rejestr zleceń i folder okresów wskazane raz; „Zmień” otwiera okno wyboru Windows na komputerze taty. */
export function FileSettingsCard({ settings }: { settings: Settings }) {
  const { chooseOrderRegister, choosePeriodsDirectory } = useSettings()

  return (
    <Card>
      <CardHeader>
        <CardTitle id="ustawienia">Ustawienia</CardTitle>
      </CardHeader>
      <CardContent>
        <ItemGroup aria-labelledby="ustawienia">
          <PathItem
            label="Rejestr zleceń"
            icon={<FileSpreadsheetIcon />}
            setting={settings.order_register}
            onChoose={chooseOrderRegister}
          />
          <PathItem
            label="Folder okresów"
            icon={<FolderIcon />}
            setting={settings.periods_directory}
            onChoose={choosePeriodsDirectory}
          />
        </ItemGroup>
      </CardContent>
    </Card>
  )
}

function PathItem({
  label,
  icon,
  setting,
  onChoose,
}: {
  label: string
  icon: React.ReactNode
  setting: PathSetting
  onChoose: () => Promise<void>
}) {
  const [choosing, setChoosing] = React.useState(false)
  const verb = setting.state === "not_set" ? "Wskaż" : "Zmień"

  const choose = () => {
    setChoosing(true)
    onChoose().finally(() => setChoosing(false))
  }

  return (
    <Item size="sm" role="group" aria-label={label}>
      <ItemMedia variant="icon" className="text-muted-foreground">
        {icon}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{label}</ItemTitle>
        <ItemDescription>
          <PathDescription setting={setting} />
        </ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button
          variant="outline"
          size="sm"
          disabled={choosing}
          aria-label={`${verb} ${label}`}
          onClick={choose}
        >
          {choosing ? <Spinner data-icon="inline-start" /> : null}
          {choosing ? "Czekam na wybór…" : verb}
        </Button>
      </ItemActions>
    </Item>
  )
}

function PathDescription({ setting }: { setting: PathSetting }) {
  switch (setting.state) {
    case "not_set":
      return <span>Nie wskazano</span>
    case "missing":
      return (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="inline-flex items-center gap-1.5 rounded-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            }
          >
            <TriangleAlertIcon className="size-4 text-warning" aria-hidden />
            Nie ma już: {setting.name}
          </TooltipTrigger>
          <TooltipContent>Brak pod ścieżką: {setting.path}</TooltipContent>
        </Tooltip>
      )
    case "ready":
      return (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            }
          >
            {setting.name}
          </TooltipTrigger>
          <TooltipContent>{setting.path}</TooltipContent>
        </Tooltip>
      )
  }
}
