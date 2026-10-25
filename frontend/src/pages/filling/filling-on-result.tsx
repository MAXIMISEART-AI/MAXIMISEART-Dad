import { ClipboardPenLineIcon } from "lucide-react"

import { ThreePartMessage } from "@/components/three-part-message"
import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { useResource } from "@/lib/use-resource"
import { FillingSkeleton, FillingSummary, quantitiesOf } from "@/pages/filling/filling-page"

/** Na karcie wyniku Przygotowania: to samo podsumowanie Uzupełnienia co jego strona, z tego samego odczytu. */
export function FillingOnResult({ token }: { token: string }) {
  // Karta powstaje, gdy Uruchomienie zmieniło pliki okresu, więc kopia sprzed niego byłaby nieaktualna.
  const { resource } = useResource(quantitiesOf(token), { fresh: true })
  const entrance = useContentEntrance(resource.state === "loading")

  return (
    <section aria-label="Uzupełnienie pliku zbiorczego" className="flex flex-col gap-3">
      <div className="flex min-h-8 items-center gap-3">
        <h3 className="text-sm font-medium">Do uzupełnienia w Excelu</h3>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          nativeButton={false}
          render={<a href={href("uzupelnienie", token)} />}
        >
          <ClipboardPenLineIcon data-icon="inline-start" />
          Uzupełnij
        </Button>
      </div>
      {resource.state === "loading" ? (
        <FillingSkeleton />
      ) : resource.state === "failed" ? null : (
        <div className={entrance}>
          {resource.data.state === "ready" ? (
            <FillingSummary token={token} found={resource.data} />
          ) : (
            <ThreePartMessage message={resource.data.message} kind="notice" />
          )}
        </div>
      )}
    </section>
  )
}
