import { expect, test, type Page } from "@playwright/test";

import { historyRows, mockApi, RUNNING_FRAMES } from "./mocks";

// Scenario 4: a mouse-free session — launch an analysis and open a historical
// report using only the keyboard. Proves tab-reachability + activation, not just
// that the handlers work.

// Tab forward until the focused element matches `selector` (bounded).
async function tabTo(page: Page, selector: string, max = 30): Promise<void> {
  for (let i = 0; i < max; i++) {
    const matched = await page.$eval(selector, (el) => el === document.activeElement).catch(() => false);
    if (matched) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`could not tab to ${selector} within ${max} steps`);
}

test("launch an analysis with the keyboard only", async ({ page }) => {
  await mockApi(page, { streamFrames: RUNNING_FRAMES, createdId: "rep-kbd" });
  await page.goto("/");
  await expect(page.getByRole("option", { name: "Anthropic" })).toBeAttached();

  // Tab to the URL field, type, and submit with Enter — no pointer.
  await tabTo(page, "#url");
  await page.keyboard.type("https://www.example-foods.com/en/recipes/hero");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/runs\/rep-kbd$/);
  await expect(page.getByTestId("stepper")).toBeVisible();
});

test("open a historical report with the keyboard only", async ({ page }) => {
  await mockApi(page, { reports: historyRows(3) });
  await page.goto("/history");
  await expect(page.getByTestId("history-table")).toBeVisible();

  // Tab to the first report permalink and activate it with Enter.
  await tabTo(page, 'a[href="/reports/rep-0"]');
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/reports\/rep-0$/);
});

test("visible focus ring is present on interactive elements", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await tabTo(page, "#url");
  // The global :focus-visible rule adds a 2px accent outline.
  const outlineWidth = await page.$eval("#url", (el) => getComputedStyle(el).outlineWidth);
  expect(parseFloat(outlineWidth)).toBeGreaterThanOrEqual(2);
});
