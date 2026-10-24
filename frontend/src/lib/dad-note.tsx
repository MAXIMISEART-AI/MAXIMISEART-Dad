import * as React from "react"

import { DadNoteForm } from "@/components/dad-note-dialog"
import { Dialog, DialogContent } from "@/components/ui/dialog"

/** Otwiera okno Uwagi taty: bez argumentu Uwagę ogólną, z identyfikatorem Uruchomienia przypiętą do niego. */
type OpenDadNote = (runId?: string) => void

type Opening = { count: number; runId: string | null }

const DadNoteContext = React.createContext<OpenDadNote | null>(null)

/** Jedno okno „Napisz do Maksa” dla nagłówka, karty Uruchomienia i Historii; każde otwarcie to nowa Uwaga. */
export function DadNoteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  const [opening, setOpening] = React.useState<Opening>({ count: 0, runId: null })

  const openNote = React.useCallback<OpenDadNote>((runId) => {
    setOpening((current) => ({ count: current.count + 1, runId: runId ?? null }))
    setOpen(true)
  }, [])

  return (
    <DadNoteContext.Provider value={openNote}>
      {children}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] gap-5 overflow-y-auto sm:max-w-lg">
          <DadNoteForm key={opening.count} openedFrom={opening.runId} close={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </DadNoteContext.Provider>
  )
}

export function useDadNote(): OpenDadNote {
  const open = React.useContext(DadNoteContext)

  if (open === null) {
    throw new Error("useDadNote poza DadNoteProvider")
  }

  return open
}
