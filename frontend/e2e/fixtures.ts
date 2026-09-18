import { test as base, expect } from "@playwright/test";

const API_BASE_URL = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.E2E_API_KEY ?? "dev-local-key";

// A page pre-configured with the backend base URL/key in localStorage,
// already navigated and reloaded once so the app picks them up - every
// test starts from a working, authenticated Jobs page.
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.goto("/");
    await page.evaluate(
      ({ url, key }) => {
        localStorage.setItem("job_fetching_service.base_url", url);
        localStorage.setItem("job_fetching_service.api_key", key);
      },
      { url: API_BASE_URL, key: API_KEY },
    );
    await page.reload();
    await use(page);
  },
});

export { expect };
