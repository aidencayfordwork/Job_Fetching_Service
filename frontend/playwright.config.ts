import { defineConfig } from "@playwright/test";

// Assumes the backend API is already running and reachable (this suite
// only manages the frontend dev server). Point E2E_API_BASE_URL /
// E2E_API_KEY at a backend with some jobs already persisted - see
// e2e/README.md.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5173",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
