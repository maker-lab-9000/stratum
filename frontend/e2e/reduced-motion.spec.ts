import { expect, test } from "@playwright/test";

import { mockApi, RUNNING_FRAMES } from "./mocks";

// Scenario 2: `prefers-reduced-motion: reduce` kills running animations. The
// live-run stepper's active step pulses; under reduce its computed
// animation-name must be "none" (the global reduced-motion rule), and animated
// with motion allowed (control).
const activeDot = ".stp.is-active .stp-dot";

async function animationName(page: import("@playwright/test").Page, selector: string) {
  return page.$eval(selector, (el) => getComputedStyle(el).animationName);
}

test("reduced-motion stops the stepper pulse animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { streamFrames: RUNNING_FRAMES });
  await page.goto("/runs/rep-e2e");
  await expect(page.locator(activeDot)).toBeVisible();
  expect(await animationName(page, activeDot)).toBe("none");
});

test("with motion allowed the stepper pulse is active (control)", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await mockApi(page, { streamFrames: RUNNING_FRAMES });
  await page.goto("/runs/rep-e2e");
  await expect(page.locator(activeDot)).toBeVisible();
  expect(await animationName(page, activeDot)).toBe("stp-pulse");
});
