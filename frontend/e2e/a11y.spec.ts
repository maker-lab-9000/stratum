import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { historyRows, mockApi, RUNNING_FRAMES } from "./mocks";

// Scenario 1: no serious/critical axe violations on any of the four views.
//
// `color-contrast` is intentionally disabled here and enforced instead by the
// deterministic src/components/contrast.test.ts, which encodes the operator's
// exact palette policy — including the accepted `--lo`-on-panel secondary-label
// exception (4.05–4.38, just under AA) that axe would otherwise flag as serious.
// This keeps axe focused on structural a11y (roles, names, ARIA, order).
async function seriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact}) @ ${v.nodes.length} node(s)`);
}

test("Launch has no serious/critical a11y violations", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("option", { name: "Anthropic" })).toBeAttached();
  expect(await seriousViolations(page)).toEqual([]);
});

test("Live run has no serious/critical a11y violations", async ({ page }) => {
  await mockApi(page, { streamFrames: RUNNING_FRAMES });
  await page.goto("/runs/rep-e2e");
  await expect(page.getByTestId("stepper")).toBeVisible();
  await expect(page.getByTestId("live-headers")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("Report (fixture) has no serious/critical a11y violations", async ({ page }) => {
  await page.goto("/dev/report");
  await expect(page.getByTestId("chain")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("History has no serious/critical a11y violations", async ({ page }) => {
  await mockApi(page, { reports: historyRows(6) });
  await page.goto("/history");
  await expect(page.getByTestId("history-table")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});
