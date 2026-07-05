import { defineConfig, devices } from "@playwright/test";

// T24 end-to-end suite. Runs against the REAL composed stack (docker-compose.e2e.yml
// brings up the api with the keyless fake LLM + a controlled target). No API
// mocking, no webServer here — `make e2e` owns the stack lifecycle.
export default defineConfig({
  testDir: "./e2e-stack",
  fullyParallel: false, // shared server-side job state; keep runs ordered
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 90_000, // a live run does DNS + warm(browser) + N samples + traceroute
  reporter: [["list"]],
  use: {
    baseURL: process.env.STRATUM_BASE_URL ?? "http://localhost:8000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
