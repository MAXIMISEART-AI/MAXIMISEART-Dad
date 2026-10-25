import { ArrowRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { href } from "@/lib/address"
import { useRuns } from "@/lib/runs"

/** Gotowość decyduje tata: przejście do Przebiegu rozliczeń z tym okresem, a start i jego potwierdzenie są tam. */
export function ReadyForSettlement({ token }: { token: string }) {
  const { setDraft } = useRuns()

  return (
    <Button
      variant="outline"
      size="lg"
      className="self-end"
      nativeButton={false}
      render={<a href={href("uruchomienia")} />}
      onClick={() => setDraft({ process: "settlement", period: token })}
    >
      Gotowe, rozlicz pracowników
      <ArrowRightIcon data-icon="inline-end" />
    </Button>
  )
}
