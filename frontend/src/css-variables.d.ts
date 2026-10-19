import type * as React from "react"

// Zmienne CSS (`--…`) są poprawnymi kluczami stylu, których React.CSSProperties nie wymienia.
declare module "react" {
  interface CSSProperties {
    [variable: `--${string}`]: string | number | undefined
  }
}
