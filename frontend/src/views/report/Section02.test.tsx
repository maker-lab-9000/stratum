import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import type { Report } from "../../api/client";
import { akamaiReport } from "../../fixtures/akamaiReport";
import { Findings } from "./Findings";
import { Progression } from "./Progression";
import { RawDrawer } from "./RawDrawer";
import { Section02 } from "./Section02";
import { TopologyChain } from "./TopologyChain";
import type { CacheVerdict, Finding, Layer } from "./types";

// --- builders ---------------------------------------------------------------

function layer(over: Partial<Layer>): Layer {
  return {
    layer_name: "L",
    vendor: "v",
    cache_type: "cache",
    role: "reverse_proxy",
    caches: true,
    state: "PASS",
    evidence_headers: ["x-cache: MISS"],
    ...over,
  };
}

function verdict(layers: Layer[], servingName: string, over: Partial<CacheVerdict> = {}): CacheVerdict {
  return {
    cached: true,
    confidence: "high",
    provider: "Test",
    provider_evidence: [],
    serving_layer: servingName,
    layer_count_to_origin: layers.filter((l) => l.caches).length,
    layers,
    sample_states: [],
    ...over,
  };
}

// --- Scenario 1: any layer count renders; flag never collides ---------------

test("2-, 5- and 7-layer chains render one node per layer (+browser), one served flag", () => {
  const shapes = [2, 5, 7];
  for (const count of shapes) {
    const layers: Layer[] = Array.from({ length: count }, (_, i) =>
      layer({
        layer_name: `Layer ${i}`,
        role: i === 0 ? "edge" : i === count - 1 ? "origin" : "reverse_proxy",
        state: i === 2 ? "HIT" : "PASS",
      }),
    );
    const serveIdx = Math.min(2, count - 1);
    const v = verdict(layers, `Layer ${serveIdx}`);
    const { container, unmount } = render(<TopologyChain verdict={v} />);

    // Browser + one node per layer.
    expect(container.querySelectorAll(".chain .node")).toHaveLength(count + 1);
    // Exactly one "served from here" flag; anchor tags are never inferred.
    expect(container.querySelectorAll(".flag")).toHaveLength(1);
    expect(container.querySelectorAll(".anchor-tag")).toHaveLength(0);
    unmount();
  }
});

// --- Scenario 2: UNKNOWN node is dashed, distinct from dimmed not-reached ----

test("UNKNOWN layer before the boundary is a dashed node, not a dimmed one", () => {
  const layers: Layer[] = [
    layer({ layer_name: "Edge", role: "edge", state: "PASS" }),
    layer({ layer_name: "Shield", role: "shield", state: "UNKNOWN" }), // ambiguous, pre-boundary
    layer({ layer_name: "Proxy", role: "reverse_proxy", state: "HIT" }), // serving
    layer({ layer_name: "Origin", role: "origin", state: "UNKNOWN" }), // beyond boundary
  ];
  const { container } = render(<TopologyChain verdict={verdict(layers, "Proxy")} />);
  const chain = within(container.querySelector(".chain") as HTMLElement);

  const unknownNode = within(chain.getByText("Shield").closest(".node") as HTMLElement);
  expect(chain.getByText("Shield").closest(".node")).toHaveClass("unknown");
  expect(unknownNode.getByText("UNKNOWN")).toBeInTheDocument();

  // The origin, though also UNKNOWN, is beyond the serving boundary -> dimmed
  // "not reached", NOT the dashed-unknown treatment.
  const originNode = chain.getByText("Origin").closest(".node") as HTMLElement;
  expect(originNode).toHaveClass("dim");
  expect(originNode).not.toHaveClass("unknown");
  expect(within(originNode).getByText("NOT REACHED")).toBeInTheDocument();
});

// --- Scenario 3: N<=6 renders columns; N>6 renders a hover strip ------------

function samples(n: number, headers: [string, string][] = [["age", "0"], ["cache-control", "no-store"]]) {
  return Array.from({ length: n }, (_, i) => ({
    request: i + 1,
    http_version: "HTTP/2",
    status: 200,
    started_at_ms: i * 2000,
    headers,
  }));
}

test("progression uses request columns at N=4 and a hover strip at N=10", () => {
  const layers = [layer({ layer_name: "Proxy", state: "HIT" })];
  const states4 = [1, 2, 3, 4].map((r) => ({ request: r, state: "MISS", evidence_headers: [] }));
  const v4 = verdict(layers, "Proxy", { sample_states: states4 });
  const { container, rerender } = render(<Progression verdict={v4} samples={samples(4)} />);

  // Four request columns, no strip.
  expect(screen.getByText("Request 1")).toBeInTheDocument();
  expect(screen.getByText("cold")).toBeInTheDocument();
  expect(container.querySelectorAll("thead th")).toHaveLength(5); // Signal + 4
  expect(container.querySelector(".strip")).toBeNull();

  // N=10 collapses the state row to a strip with per-request hover titles.
  const states10 = Array.from({ length: 10 }, (_, i) => ({
    request: i + 1,
    state: i === 0 ? "MISS" : "HIT",
    evidence_headers: [],
  }));
  const v10 = verdict(layers, "Proxy", { sample_states: states10 });
  rerender(<Progression verdict={v10} samples={samples(10)} />);
  const strip = container.querySelector(".strip");
  expect(strip).not.toBeNull();
  expect(strip!.querySelectorAll("i")).toHaveLength(10);
  expect(within(strip as HTMLElement).getByTitle("Request 1: MISS")).toBeInTheDocument();
  expect(within(strip as HTMLElement).getByTitle("Request 10: HIT")).toBeInTheDocument();
});

// --- Scenario 4: findings collapse past 3, severity-sorted ------------------

test("9 findings -> top 3 shown severity-first, 'show all (9)' expands the rest", async () => {
  const user = userEvent.setup();
  const mk = (severity: Finding["severity"], n: number): Finding[] =>
    Array.from({ length: n }, (_, i) => ({
      severity,
      title: `${severity}-${i}`,
      description: "d",
      evidence_header: "Age: 0",
    }));
  // Deliberately unsorted: 3 info, 3 warning, 3 critical.
  const security = [...mk("info", 3), ...mk("warning", 3), ...mk("critical", 3)];
  render(<Findings security={security} performance={[]} />);

  // Only the top 3 render; the button advertises the full count.
  expect(screen.getAllByText(/^(critical|warning|info)-\d$/)).toHaveLength(3);
  const btn = screen.getByRole("button", { name: "show all (9)" });

  // Severity-first: the three visible are the criticals.
  expect(screen.getByText("critical-0")).toBeInTheDocument();
  expect(screen.queryByText("info-0")).not.toBeInTheDocument();
  // Count label reflects every finding, not just the visible ones.
  expect(screen.getByText("· 3 critical · 3 warning · 3 info")).toBeInTheDocument();

  await user.click(btn);
  expect(screen.getAllByText(/^(critical|warning|info)-\d$/)).toHaveLength(9);
  expect(screen.getByText("info-0")).toBeInTheDocument();
});

// --- Scenario 5: chain flips to a vertical timeline below ~700px -------------

test("the chain has a mobile vertical-timeline rule (no horizontal scroll)", () => {
  const css = readFileSync(resolve(process.cwd(), "src", "index.css"), "utf8");
  const media = css.match(/@media\s*\(max-width:\s*700px\)\s*\{([\s\S]*?)\n\}/);
  expect(media, "expected a max-width:700px breakpoint").not.toBeNull();
  expect(media![1]).toMatch(/\.chain\s*\{[^}]*flex-direction:\s*column/);
  expect(media![1]).toMatch(/\.chain\s*\{[^}]*overflow:\s*visible/);
});

// --- Scenario 6: header/evidence values are inert text (XSS) -----------------

test("an injection probe in a header value renders as text, never as markup", () => {
  const probe = '<img src=x onerror="alert(1)">';
  const xssReport: Report = {
    ...akamaiReport,
    samples_json: [
      { request: 1, http_version: "HTTP/2", status: 200, headers: [["x-evil", probe]] },
    ] as unknown as Report["samples_json"],
    verdict_json: {
      ...(akamaiReport.verdict_json as object),
      layers: [layer({ layer_name: "Proxy", state: "HIT", evidence_headers: [`x-evil: ${probe}`] })],
      serving_layer: "Proxy",
      validation: { ok: true, flags: [] },
    } as unknown as Report["verdict_json"],
  };

  const { container } = render(<Section02 report={xssReport} />);

  // No live <img> was ever created from the payload.
  expect(container.querySelector("img")).toBeNull();
  // The literal probe text is present (escaped) in both the raw drawer and the
  // topology node evidence.
  expect(screen.getAllByText((_, el) => el?.textContent?.includes(probe) ?? false).length).toBeGreaterThan(0);
});

test("RawDrawer switches to a <select> beyond 8 requests", () => {
  render(<RawDrawer samples={samples(10)} />);
  expect(screen.getByLabelText("Select request")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Request 1/ })).not.toBeInTheDocument();
});
