import { expect, test } from "@playwright/test";

// End-to-end against the live compose stack (real api + fake LLM + target site).
// The api samples the `target` service over the compose network; the browser
// only talks to the api UI on :8000.
const TARGET = "http://target:8080/";

async function launch(page: import("@playwright/test").Page, url: string) {
  await page.goto("/");
  await expect(page.getByRole("option", { name: "Fake (recorded)" })).toBeAttached();
  await page.locator("#url").fill(url);
  await page.getByRole("button", { name: /Run analysis/i }).click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByTestId("stepper")).toBeVisible();
  // The live run hands off to the report on the terminal event.
  await page.waitForURL(/\/reports\//, { timeout: 80_000 });
}

test("happy path: launch → live → report (serving layer + progression) → history", async ({ page }) => {
  await launch(page, TARGET);

  // Verdict came from the fake, cited the target's real headers, and validated.
  await expect(page.getByText("Edge Cache").first()).toBeVisible();

  // Progression reflects the target's configured headers end to end: no-cache
  // Cache-Control and a growing Age (sampler → UI integrity).
  const prog = page.locator("table.prog");
  await expect(prog).toBeVisible();
  await expect(prog.getByText(/no-cache/)).toBeVisible();
  await expect(prog.getByRole("rowheader", { name: "Age" })).toBeVisible();

  // Raw evidence is present (the drawer shows the target's Server header).
  await expect(page.getByText("Raw response headers")).toBeVisible();

  // History now has a row for this analysis, opening the report.
  await page.goto("/history");
  const table = page.getByTestId("history-table");
  await expect(table).toBeVisible();
  await expect(table.getByText(TARGET, { exact: true }).first()).toBeVisible();
  await table.locator(".hist-url a").first().click();
  await expect(page).toHaveURL(/\/reports\//);
});

test("degraded path: fake LLM fails → evidence + degraded banner, no crash", async ({ page }) => {
  // The sentinel path makes the fake return unparseable output → degraded verdict.
  await launch(page, "http://target:8080/__degrade__");

  await expect(page.getByText("Verdict unavailable.")).toBeVisible();
  // Measured evidence still renders (the report is never empty, §8.3).
  await expect(page.getByText("Raw response headers")).toBeVisible();
  await expect(page.locator(".dns")).toBeVisible();
});
