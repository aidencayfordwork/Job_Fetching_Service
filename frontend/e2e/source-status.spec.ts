import { expect, test } from "./fixtures";

test.describe("Source Status page", () => {
  test("shows stats tiles and the per-source health table", async ({ page }) => {
    await page.click('a:has-text("Source Status")');

    await expect(page.locator(".source-table")).toBeVisible({ timeout: 15_000 });
    const rowCount = await page.locator(".source-table tbody tr").count();
    expect(rowCount).toBeGreaterThan(0);

    // Every seeded source shows a status pill, whatever its value.
    await expect(page.locator(".status-pill").first()).toBeVisible();

    const statTiles = page.locator(".stat-tile");
    await expect(statTiles).toHaveCount(4);
    for (const label of ["Total active jobs", "Added today", "Added last 24h", "Last fetch"]) {
      await expect(page.locator(".stat-label", { hasText: label })).toBeVisible();
    }
  });
});
