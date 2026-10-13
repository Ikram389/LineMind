/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Inside Docker the backend is reachable by its service name.
const backendUrl = process.env.VITE_BACKEND_URL ?? "http://backend:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // File-change events don't cross from Windows into Docker; polling makes hot reload work.
    watch: { usePolling: true },
    // The browser talks only to the Vite server, which forwards API calls and WebSockets
    // to Django (same origin, so no CORS setup is needed).
    proxy: {
      "/api": backendUrl,
      "/ws": { target: backendUrl.replace(/^http/, "ws"), ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
