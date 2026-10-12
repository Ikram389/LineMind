import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Inside Docker the backend is reachable by its service name.
const backendUrl = process.env.VITE_BACKEND_URL ?? "http://backend:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // File-change events don't cross from Windows into Docker; polling makes hot reload work.
    watch: { usePolling: true },
    // The browser calls /api on the Vite server, which forwards it to Django (no CORS needed).
    proxy: {
      "/api": backendUrl,
    },
  },
});
