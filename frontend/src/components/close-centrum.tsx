import * as React from "react"
import { PowerIcon, PowerOffIcon } from "lucide-react"

import { closeCentrum } from "@/api/centrum"
import { failureMessage } from "@/api/client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar"
import { Spinner } from "@/components/ui/spinner"
import { toast } from "@/components/ui/toast"

const BACK_WITH_SHORTCUT = "Wrócisz skrótem „Centrum rozliczeń” na pulpicie."

/**
 * „Zamknij Centrum rozliczeń” w stopce menu. Zamknięcie karty nie wyłącza serwera, robi to tylko ten przycisk.
 * Odmowa serwera (np. w trakcie Uruchomienia procesu) wraca jako powiadomienie z jego komunikatem.
 */
export function CloseCentrumButton({ onClosed }: { onClosed: () => void }) {
  const [open, setOpen] = React.useState(false)
  const [closing, setClosing] = React.useState(false)

  function close() {
    setClosing(true)
    closeCentrum().then(onClosed, (failure: Error) => {
      setClosing(false)
      setOpen(false)
      toast.add({
        title: "Nie zamknięto Centrum rozliczeń",
        description: failureMessage(failure),
        type: "error",
      })
    })
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton tooltip="Zamknij Centrum rozliczeń" onClick={() => setOpen(true)}>
            <PowerIcon />
            <span>Zamknij Centrum rozliczeń</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <AlertDialog open={open} onOpenChange={(next) => setOpen(next || closing)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Zamknąć Centrum rozliczeń?</AlertDialogTitle>
            <AlertDialogDescription>{BACK_WITH_SHORTCUT}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={closing}>Anuluj</AlertDialogCancel>
            <AlertDialogAction disabled={closing} onClick={close}>
              {closing ? <Spinner data-icon="inline-start" /> : null}
              Zamknij Centrum
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

/** Ekran po zamknięciu: serwer już nie działa, więc karta nie ma czego odświeżać. */
export function CentrumClosed() {
  return (
    <main className="wejscie flex min-h-svh items-center justify-center p-6">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PowerOffIcon />
          </EmptyMedia>
          <EmptyTitle>
            <h1>Centrum rozliczeń jest zamknięte</h1>
          </EmptyTitle>
          <EmptyDescription>Możesz zamknąć tę kartę. {BACK_WITH_SHORTCUT}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    </main>
  )
}
