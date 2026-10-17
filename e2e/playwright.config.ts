import { defineConfig } from "@playwright/test";

// Runs inside the e2e container, which shares the frontend container's network.
export default defineConfig({
  testDir: "tests",
  timeout: 20 * 60_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    locale: "en-GB",
    // The container's own Chromium (see Dockerfile).
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
});
