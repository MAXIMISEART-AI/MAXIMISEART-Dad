import * as React from "react"

import { failureMessage } from "@/api/client"
import {
  changeTheme,
  chooseOrderRegister,
  choosePeriodsDirectory,
  getSettings,
  type Choice,
  type PathSetting,
  type Settings,
  type Theme,
} from "@/api/centrum"
import { toast } from "@/components/ui/toast"
import { forgetLastReads, useResource, type Resource } from "@/lib/use-resource"

// Kopia motywu w przeglądarce tylko na pierwsze malowanie (index.html); źródłem prawdy są ustawienia na serwerze.
const THEME_KEY = "centrum-rozliczen-motyw"

/** Plik taty wskazywany natywnym oknem wyboru: pole Ustawień taty, które jest ścieżką. */
export type PickedPath = { [Key in keyof Settings]: Settings[Key] extends PathSetting ? Key : never }[keyof Settings]

type SettingsContextValue = {
  settings: Resource<Settings>
  theme: Theme
  /** Plik, którego okno wyboru jest teraz otwarte; dopóki jest, żaden przycisk nie otwiera drugiego. */
  picker: PickedPath | null
  choose: (path: PickedPath) => void
  toggleTheme: () => void
}

const PICKERS: Record<PickedPath, () => Promise<Choice>> = {
  order_register: chooseOrderRegister,
  periods_directory: choosePeriodsDirectory,
}

const SettingsContext = React.createContext<SettingsContextValue | null>(null)

function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

/** Zmiana motywu jest natychmiastowa: przejścia są wyłączone na jedną klatkę, żeby nic nie mrugało. */
function applyTheme(theme: Theme) {
  const root = document.documentElement
  const freeze = document.createElement("style")

  freeze.textContent = "*,*::before,*::after{transition:none!important}"
  document.head.append(freeze)
  root.classList.toggle("dark", theme === "dark")
  root.style.colorScheme = theme
  localStorage.setItem(THEME_KEY, theme)
  window.getComputedStyle(root).getPropertyValue("color")
  requestAnimationFrame(() => requestAnimationFrame(() => freeze.remove()))
}

/**
 * Tożsamość plików taty, z których serwer czyta strony: folder okresów i Rejestr zleceń, bez motywu.
 * Inna tożsamość to nowy odczyt stron (klucz ich treści); zmiana motywu niczego nie czyta ponownie.
 */
export function filesIdentity(settings: Settings): string {
  return JSON.stringify([settings.periods_directory, settings.order_register])
}

function files(settings: Resource<Settings>): string | null {
  return settings.state === "ready" ? filesIdentity(settings.data) : null
}

function showFailure(failure: Error) {
  toast.add({ title: "Nie udało się", description: failureMessage(failure), type: "error" })
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const { resource: settings, replace } = useResource(getSettings)
  const [firstPaintTheme] = React.useState<Theme>(currentTheme)
  const [chosenTheme, setChosenTheme] = React.useState<Theme | null>(null)
  const savedTheme = settings.state === "ready" ? settings.data.theme : null
  const theme = chosenTheme ?? savedTheme ?? firstPaintTheme

  React.useEffect(() => {
    if (theme !== currentTheme()) {
      applyTheme(theme)
    }
  }, [theme])

  // Jedno okno wyboru naraz, wspólne dla wszystkich stron: tata klika dwa razy z przyzwyczajenia, a okno Windows
  // pojawia się po chwili, więc drugie kliknięcie (albo „Zmień” przy drugim pliku) otworzyłoby drugie okno.
  const openPicker = React.useRef<PickedPath | null>(null)
  const [picker, setPicker] = React.useState<PickedPath | null>(null)

  const remember = React.useCallback(
    (choice: Choice) => {
      const chosen: Resource<Settings> = { state: "ready", data: choice.settings }

      // Ostatnie dane stron pochodzą z poprzednich plików, więc nie mogą się pokazać jako bieżące.
      if (files(chosen) !== files(settings)) {
        forgetLastReads()
      }

      replace(chosen)
    },
    [replace, settings]
  )

  const value = React.useMemo<SettingsContextValue>(
    () => ({
      settings,
      theme,
      picker,
      choose: (path) => {
        if (openPicker.current !== null) {
          return
        }

        openPicker.current = path
        setPicker(path)
        PICKERS[path]()
          .then(remember, showFailure)
          .finally(() => {
            openPicker.current = null
            setPicker(null)
          })
      },
      toggleTheme: () => {
        const next = theme === "dark" ? "light" : "dark"

        setChosenTheme(next)
        changeTheme(next).then((saved) => replace({ state: "ready", data: saved }), showFailure)
      },
    }),
    [settings, theme, picker, remember, replace]
  )

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings() {
  const context = React.useContext(SettingsContext)

  if (context === null) {
    throw new Error("useSettings działa tylko wewnątrz SettingsProvider.")
  }

  return context
}
