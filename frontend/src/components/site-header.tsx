import { MoonIcon, SunIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useSettings } from "@/lib/settings"

// Nagłówek bez tytułu (tytuł jest w treści strony): menu i jedna ikona motywu.
export function SiteHeader() {
  const { theme, toggleTheme } = useSettings()
  const dark = theme === "dark"
  const label = dark ? "Włącz motyw jasny" : "Włącz motyw ciemny"

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 px-4 lg:px-6">
      <SidebarTrigger className="-ml-1" aria-label="Pokaż lub ukryj menu" />
      <div className="ml-auto flex items-center gap-2">
        <Tooltip>
          <TooltipTrigger
            render={<Button variant="ghost" size="icon" aria-label={label} onClick={toggleTheme} />}
          >
            {dark ? <SunIcon /> : <MoonIcon />}
          </TooltipTrigger>
          <TooltipContent>{dark ? "Motyw jasny" : "Motyw ciemny"}</TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}
