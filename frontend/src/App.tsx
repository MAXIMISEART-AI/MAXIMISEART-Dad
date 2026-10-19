import type * as React from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/toast"
import { TooltipProvider } from "@/components/ui/tooltip"
import { RunsProvider } from "@/lib/runs"
import { SettingsProvider } from "@/lib/settings"
import { useCurrentPage } from "@/pages"

// SAFETY: zmienne CSS (`--…`) są poprawnymi kluczami stylu, których CSSProperties nie wymienia.
const LAYOUT = {
  "--sidebar-width": "calc(var(--spacing) * 66)",
  "--header-height": "calc(var(--spacing) * 14)",
} as React.CSSProperties

export function App() {
  const page = useCurrentPage()

  return (
    <SettingsProvider>
      <TooltipProvider>
        <Toaster>
          <RunsProvider>
          <SidebarProvider style={LAYOUT}>
            <AppSidebar variant="inset" current={page} />
            <SidebarInset>
              <SiteHeader />
              <div className="@container/main mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 pb-10 lg:px-8">
                <page.Content />
              </div>
            </SidebarInset>
          </SidebarProvider>
          </RunsProvider>
        </Toaster>
      </TooltipProvider>
    </SettingsProvider>
  )
}
