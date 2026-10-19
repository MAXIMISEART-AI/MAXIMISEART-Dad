import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

export type FilterOption<T extends string> = { value: T; label: string }

/** Jeden wybór z kilku (filtr): zawsze jedna opcja wciśnięta, przełączanie bez animacji. */
export function SegmentedFilter<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: ReadonlyArray<FilterOption<T>>
  value: T
  onChange: (value: T) => void
}) {
  return (
    <ToggleGroup
      aria-label={label}
      variant="outline"
      spacing={0}
      value={[value]}
      onValueChange={(pressed) => {
        // Ponowne kliknięcie wciśniętej opcji niczego nie zmienia: filtr zawsze ma wartość.
        const chosen = options.find((option) => option.value === pressed[0])

        if (chosen !== undefined) {
          onChange(chosen.value)
        }
      }}
    >
      {options.map((option) => (
        <ToggleGroupItem key={option.value} value={option.value}>
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
