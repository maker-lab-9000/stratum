import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

// T23 scenario 3: the status/label palette meets the §8 quality floor. We parse
// the real :root tokens and compute WCAG 2.1 contrast ratios, so a token edit
// that dropped a data label below the floor would fail here.
//
// Decision (operator, 2026-07-05): keep the mockup's exact `--lo` (#6e8496)
// rather than brighten it. `--lo` clears 4.5:1 on the page background (--bg) and
// is the accepted *secondary* tier on the panel surfaces (4.38 on --panel,
// 4.05 on --panel-2 — just under AA, used for de-emphasised labels). Primary
// data labels use --mid / --hi, which pass comfortably everywhere. This test
// encodes exactly that contract.

function parseRoot(css: string): Record<string, string> {
  const match = css.match(/:root\s*\{([\s\S]*?)\}/);
  const out: Record<string, string> = {};
  if (!match) return out;
  for (const decl of match[1].split(";")) {
    const idx = decl.indexOf(":");
    if (idx === -1) continue;
    const name = decl.slice(0, idx).trim();
    if (name.startsWith("--")) out[name] = decl.slice(idx + 1).trim();
  }
  return out;
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  const n = parseInt(hex.replace("#", ""), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

function contrast(fg: string, bg: string): number {
  const a = luminance(fg);
  const b = luminance(bg);
  const [hi, lo] = a >= b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

const tokens = parseRoot(readFileSync(resolve(process.cwd(), "src", "index.css"), "utf8"));
const AA = 4.5;

describe("status/label palette contrast (WCAG AA, §8 quality floor)", () => {
  // Primary data-label tiers must clear AA on every surface they render on.
  const surfaces: [string, string][] = [
    ["--bg", tokens["--bg"]],
    ["--panel", tokens["--panel"]],
    ["--panel-2", tokens["--panel-2"]],
  ];

  test.each(surfaces)("--mid is AA on %s", (_name, bg) => {
    expect(contrast(tokens["--mid"], bg)).toBeGreaterThanOrEqual(AA);
  });

  test.each(surfaces)("--hi is AA on %s", (_name, bg) => {
    expect(contrast(tokens["--hi"], bg)).toBeGreaterThanOrEqual(AA);
  });

  // Status colors used as text/icons on their own tinted chips + on the page.
  test("--accent, --hit, --miss, --crit clear AA on --bg", () => {
    for (const t of ["--accent", "--hit", "--miss", "--crit"]) {
      expect(contrast(tokens[t], tokens["--bg"]), t).toBeGreaterThanOrEqual(AA);
    }
  });

  // --lo: AA on the page background; a documented secondary tier on panels.
  test("--lo clears AA on the page background", () => {
    expect(contrast(tokens["--lo"], tokens["--bg"])).toBeGreaterThanOrEqual(AA);
  });

  test("--lo stays near AA on panels (accepted secondary-label exception)", () => {
    // Guards against a regression that would push the dim tier well below AA.
    // (~4.4/4.05 today; large-text AA is 3:1, which it clears with margin.)
    expect(contrast(tokens["--lo"], tokens["--panel"])).toBeGreaterThanOrEqual(4.0);
    expect(contrast(tokens["--lo"], tokens["--panel-2"])).toBeGreaterThanOrEqual(3.0);
  });
});
