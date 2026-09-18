import { expect, test } from "./fixtures";

test.describe("Jobs page", () => {
  test("loads job cards from the real API", async ({ page }) => {
    await expect(page.locator(".error-banner")).toHaveCount(0);
    await expect(page.locator(".job-card").first()).toBeVisible({ timeout: 15_000 });

    const count = await page.locator(".job-card").count();
    expect(count).toBeGreaterThan(0);

    // Every card should show the fields the job-card spec requires.
    const first = page.locator(".job-card").first();
    await expect(first.locator("h3")).not.toBeEmpty();
    await expect(first.locator(".job-card-subtitle")).not.toBeEmpty();
  });

  test("filtering by level narrows results to that level only", async ({ page }) => {
    await expect(page.locator(".job-card").first()).toBeVisible({ timeout: 15_000 });

    await page.selectOption("select", "SENIOR");
    await expect(page.locator(".results-count")).toBeVisible();

    const badges = page.locator(".job-card .badge-level");
    const badgeCount = await badges.count();
    if (badgeCount === 0) {
      test.skip(true, "no SENIOR-level jobs in this backend's current data");
    }
    for (let i = 0; i < badgeCount; i++) {
      await expect(badges.nth(i)).toHaveText("SENIOR");
    }
  });

  test("pagination advances to the next page", async ({ page }) => {
    await expect(page.locator(".job-card").first()).toBeVisible({ timeout: 15_000 });

    const nextButton = page.locator('.pagination button:has-text("Next")');
    if (await nextButton.isDisabled()) {
      test.skip(true, "fewer jobs than one page - nothing to paginate to");
    }

    await nextButton.click();
    await expect(page.locator(".pagination span")).toHaveText(/Page 2 of/);
  });

  test("View JD opens a modal with the full job description", async ({ page }) => {
    await expect(page.locator(".job-card").first()).toBeVisible({ timeout: 15_000 });

    await page.locator('button:has-text("View JD")').first().click();
    await expect(page.locator(".modal")).toBeVisible();
    await expect(page.locator(".modal-jd")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".modal-jd")).not.toBeEmpty();

    await page.locator(".modal-close").click();
    await expect(page.locator(".modal")).toHaveCount(0);
  });
});
