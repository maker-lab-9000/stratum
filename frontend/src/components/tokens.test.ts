import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "vitest";

// T15 scenario 1: the app's :root tokens must equal the mockup's, so the theme
// never drifts from the visual source of truth. The mockup is operator-local
// (git-ignored); where present, this test enforces parity.
function parseRoot(css: string): Record<string, string> {
  const match = css.match(/:root\s*\{([\s\S]*?)\}/);
  const out: Record<string, string> = {};
  if (!match) return out;
  for (const decl of match[1].split(";")) {
    const idx = decl.indexOf(":");
    if (idx === -1) continue;
    const name = decl.slice(0, idx).trim();
    if (!name.startsWith("--")) continue;
    out[name] = decl.slice(idx + 1).replace(/\s+/g, ""); // ignore whitespace
  }
  return out;
}

const mockupPath = resolve(process.cwd(), "..", "cache-report-mockup.html");
const indexCssPath = resolve(process.cwd(), "src", "index.css");

test.runIf(existsSync(mockupPath))("index.css :root matches the mockup tokens", () => {
  const mockup = parseRoot(readFileSync(mockupPath, "utf8"));
  const ours = parseRoot(readFileSync(indexCssPath, "utf8"));

  expect(Object.keys(mockup).length).toBeGreaterThan(15);
  for (const [name, value] of Object.entries(mockup)) {
    expect(ours[name], `token ${name}`).toBe(value);
  }
});

test("index.css defines the core color tokens with the mockup hex values", () => {
  // A committed sanity check that runs even without the mockup present.
  const ours = parseRoot(readFileSync(indexCssPath, "utf8"));
  expect(ours["--bg"]).toBe("#0e1419");
  expect(ours["--accent"]).toBe("#5b9df0");
  expect(ours["--hit"]).toBe("#54d98c");
  expect(ours["--miss"]).toBe("#f0b34a");
  expect(ours["--crit"]).toBe("#f4736b");
});
