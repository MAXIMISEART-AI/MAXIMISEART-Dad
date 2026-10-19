import { cn } from "cn"
import { Loader2Icon } from "lucide-react"

function Spinner({ className, ...props }: React.ComponentProps<"svg">) {
  return (
    <Loader2Icon data-slot="spinner" role="status" aria-label="Trwa" className={cn("size-4 animate-spin [animation-duration:750ms]", className)} {...props} />
  )
}

export { Spinner }
