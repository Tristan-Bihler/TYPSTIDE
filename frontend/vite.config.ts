import { defineConfig } from "vitest/config";

// Keep in sync with [server] in ../config.toml.
const FRONTEND_PORT = 5173;
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      "/api": BACKEND,
      "/ws": { target: BACKEND, ws: true },
    },
  },
  // Pre-bundle at startup; otherwise Vite discovers these on first load and reloads
  // the page, which closes any dialog the user already opened.
  optimizeDeps: {
    include: [
      "@codemirror/autocomplete",
      "@codemirror/commands",
      "@codemirror/language",
      "@codemirror/lint",
      "@codemirror/search",
      "@codemirror/state",
      "@codemirror/view",
      "@lezer/highlight",
    ],
  },
  test: {
    environment: "node",
  },
});
