import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "vitest";

// T15 scenario 4: green (--hit) is reserved for HIT / served-from-cache. It must
// never appear in a structural rule — only in status selectors. This scans the
// ported CSS and asserts every green-using rule is a status rule.
const GREEN = /var\(--hit\b|--hit-bg|#54d98c|84,\s*217,\s*140/;
const ALLOWED = /is-hit|\bhit\b|served|origin|\bflag\b|\bboundary\b|strip i\.h/;

test("green tokens appear only in HIT/served status rules", () => {
  const css = readFileSync(resolve(process.cwd(), "src", "index.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, ""); // strip comments so they don't glue onto selectors
  const offenders: string[] = [];

  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = match[1].trim();
    const body = match[2];
    // Skip token definitions and at-rules — those legitimately define green.
    if (selector.startsWith("@") || selector.startsWith(":root") || selector.startsWith("*")) {
      continue;
    }
    if (GREEN.test(body) && !ALLOWED.test(selector)) {
      offenders.push(selector);
    }
  }

  expect(offenders, `green leaked into structural rules: ${offenders.join(" | ")}`).toEqual([]);
});
