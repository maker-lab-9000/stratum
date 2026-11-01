import { expect, test, type Page } from "@playwright/test";

import { historyRows, LONG_MODELS, longReport, mockApi, RUNNING_FRAMES } from "./mocks";

// Scenario 5: the layout holds at desktop (1280) and mobile (390) — the mockup's
// two reference widths. A committed pixel baseline is deliberately avoided
// (cross-machine font/render drift); instead we assert the invariants that a
// visual regression would break — no page-level horizontal scroll and the key
// regions present — and capture screenshots as build artifacts for eyeballing
// against the mockup.
const WIDTHS = [
  { label: "desktop", width: 1280, height: 900 },
  { label: "mobile", width: 390, height: 900 },
];

async function noHorizontalScroll(page: Page) {
  // The page itself must not scroll sideways; inner .tbl-wrap/.chain may.
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

for (const { label, width, height } of WIDTHS) {
  test(`report holds at ${label} (${width}px), no page h-scroll`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await page.goto("/dev/report");
    await expect(page.locator(".strata")).toBeVisible();
    // Key regions of the report are all present.
    await expect(page.getByRole("heading", { name: "What the requests showed" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What to look at" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Where it's hosted" })).toBeVisible();
    await expect(page.locator(".drawer")).toBeVisible();
    expect(await noHorizontalScroll(page)).toBe(true);
    await testInfo.attach(`report-${label}`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });
}

test("launch, history and live hold at 390px with no page h-scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });

  await mockApi(page, { reports: historyRows(5), streamFrames: RUNNING_FRAMES });

  await page.goto("/");
  await expect(page.getByRole("option", { name: "Anthropic" })).toBeAttached();
  expect(await noHorizontalScroll(page)).toBe(true);

  await page.goto("/history");
  await expect(page.getByTestId("history-table")).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  await page.goto("/runs/rep-e2e");
  await expect(page.getByTestId("stepper")).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);
});

test("report with long values has no horizontal scroll at 390", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApi(page, { report: longReport() });
  await page.goto("/reports/long");
  await expect(page.locator(".strata")).toBeVisible();
  await expect(page.getByRole("heading", { name: "What the requests showed" })).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);
});

test("launch with a long model list has no horizontal scroll at 390", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockApi(page, { models: LONG_MODELS });
  await page.goto("/");
  await expect(page.locator("#model")).toBeAttached();
  expect(await noHorizontalScroll(page)).toBe(true);
});
