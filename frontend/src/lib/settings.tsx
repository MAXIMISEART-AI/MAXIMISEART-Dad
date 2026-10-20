import * as React from "react"

import { failureMessage } from "@/api/client"
import {
  changeTheme,
  chooseOrderRegister,
  choosePeriodsDirectory,
  getSettings,
  type Choice,
  type Settings,
  type Theme,
} from "@/api/centrum"
import { toast } from "@/components/ui/toast"
import { forgetLastReads, useResource, type Resource } from "@/lib/use-resource"

// Kopia motywu w przeglądarce tylko na pierwsze malowanie (index.html); źródłem prawdy są ustawienia na serwerze.
const THEME_KEY = "centrum-rozliczen-motyw"

type SettingsContextValue = {
  settings: Resource<Settings>
  theme: Theme
  chooseOrderRegister: () => Promise<void>
  choosePeriodsDirectory: () => Promise<void>
  toggleTheme: () => void
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

/** Pliki taty, z których serwer czyta strony: folder okresów i Rejestr zleceń (bez motywu). */
function files(settings: Resource<Settings>): string | null {
  return settings.state === "ready"
    ? JSON.stringify([settings.data.periods_directory, settings.data.order_register])
    : null
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
      chooseOrderRegister: () => chooseOrderRegister().then(remember, showFailure),
      choosePeriodsDirectory: () => choosePeriodsDirectory().then(remember, showFailure),
      toggleTheme: () => {
        const next = theme === "dark" ? "light" : "dark"

        setChosenTheme(next)
        changeTheme(next).then((saved) => replace({ state: "ready", data: saved }), showFailure)
      },
    }),
    [settings, theme, remember, replace]
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
