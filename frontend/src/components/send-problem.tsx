import { cn } from "cn"
import { CircleAlertIcon } from "lucide-react"

/** Czym jest wiadomość taty, której nie da się wysłać: Uwaga jest rodzaju żeńskiego, Zgłoszenie nijakiego. */
type Kind = "uwaga" | "zgloszenie"

/**
 * Dlaczego wiadomość nie wychodzi, choć tata nic tu nie poprawi: Tokenu do Zgłoszeń nie ma albo Skrzynka go odrzuca
 * (`key`, wiadomość czeka na komputerze i wyjdzie sama, gdy Maks naprawi token), albo Skrzynka odrzuciła jej treść.
 */
export type SendCause = "key" | "rejected"

const TOKEN = "Token do Zgłoszeń nie działa. Skontaktuj się z Maksem."

const TEXTS: Record<SendCause, Record<Kind, string>> = {
  key: { uwaga: TOKEN, zgloszenie: TOKEN },
  rejected: {
    uwaga: "Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem.",
    zgloszenie: "Tego Zgłoszenia nie da się wysłać. Skontaktuj się z Maksem.",
  },
}

/**
 * Jeden element dla okna Uwagi taty, Zgłoszenia i Powiadomień: ikona błędu i zdanie, że trzeba się skontaktować z
 * Maksem, bez obietnicy, że wiadomość wyjdzie, gdy będzie internet. Miejsce wybiera tylko wielkość i układ.
 */
export function SendProblem({
  cause,
  kind,
  className,
  iconClassName,
  role,
}: {
  cause: SendCause
  kind: Kind
  className?: string
  iconClassName?: string
  role?: "status"
}) {
  return (
    <p role={role} className={cn("flex items-center gap-2 text-sm text-foreground", className)}>
      <CircleAlertIcon className={cn("size-4 shrink-0 text-destructive", iconClassName)} aria-hidden />
      {TEXTS[cause][kind]}
    </p>
  )
}
