import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Zbudowany frontend trafia do pakietu Pythona i jest commitowany: u taty nie ma Node.
const CENTRUM = "http://127.0.0.1:47811"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: resolve(import.meta.dirname, "../src/rozliczenia/centrum/static"),
    emptyOutDir: true,
    // Serwowane z dysku taty, nie z sieci: jeden pakiet bez dzielenia jest prostszy i wystarczająco szybki.
    chunkSizeWarningLimit: 1024,
    // Stałe nazwy zamiast hasha, żeby gałęzie scalały te same pliki; świeżość u taty daje ETag (`_Frontend` w app.py).
    rolldownOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    // `npm run dev` obok działającego `run_centrum.py --no-browser`: API idzie do serwera Centrum,
    // który przyjmuje akcje tylko z własnym `Origin`.
    proxy: {
      "/api": {
        target: CENTRUM,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => request.setHeader("origin", CENTRUM))
        },
      },
    },
  },
})
