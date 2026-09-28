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
  test: {
    environment: "node",
  },
});
