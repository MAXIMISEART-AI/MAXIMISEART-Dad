import type * as React from "react"
import { ReceiptTextIcon } from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { PAGES, pageHref, type Page } from "@/pages"

export function AppSidebar({
  current,
  ...props
}: React.ComponentProps<typeof Sidebar> & { current: Page }) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<a href={pageHref(PAGES[0])} />}>
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <ReceiptTextIcon className="size-4" />
              </span>
              <span className="text-base font-semibold">Centrum rozliczeń</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu aria-label="Sekcje Centrum rozliczeń">
              {PAGES.map((page) => (
                <SidebarMenuItem key={page.id}>
                  <SidebarMenuButton
                    isActive={page.id === current.id}
                    tooltip={page.title}
                    render={
                      <a
                        href={pageHref(page)}
                        aria-current={page.id === current.id ? "page" : undefined}
                      />
                    }
                  >
                    <page.icon />
                    <span>{page.title}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
