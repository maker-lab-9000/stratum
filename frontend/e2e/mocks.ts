import type { Page } from "@playwright/test";

import { akamaiReport } from "../src/fixtures/akamaiReport";

// Single API stub for the e2e run — no backend. Branches on method + path so
// route-precedence never bites. Every view gets exactly the shape it reads.
export interface ApiOpts {
  models?: unknown;
  reports?: unknown[];
  report?: unknown;
  createdId?: string;
  streamFrames?: object[];
}

const PROVIDERS = {
  providers: [
    { id: "anthropic", name: "Anthropic", models: [{ id: "claude-opus-4-8", name: "Claude Opus 4.8" }] },
  ],
};

function sse(frames: object[]): string {
  return frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
}

export async function mockApi(page: Page, opts: ApiOpts = {}): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const method = req.method();

    if (path === "/api/models") return route.fulfill({ json: opts.models ?? PROVIDERS });
    if (path.endsWith("/stream")) {
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
        body: sse(opts.streamFrames ?? []),
      });
    }
    if (path === "/api/analyses" && method === "POST") {
      return route.fulfill({ status: 201, json: { id: opts.createdId ?? "rep-e2e" } });
    }
    if (path === "/api/analyses") return route.fulfill({ json: { reports: opts.reports ?? [] } });
    if (/^\/api\/analyses\/[^/]+$/.test(path) && method === "GET") {
      return route.fulfill({ json: opts.report ?? {} });
    }
    if (path.endsWith("/cancel") && method === "POST") {
      return route.fulfill({ json: { id: path.split("/")[3], status: "error" } });
    }
    if (method === "DELETE") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ status: 404, json: { detail: "not found" } });
  });
}

// A run that has collected all evidence and is analysing (no terminal event, so
// the live view stays put for inspection).
export const RUNNING_FRAMES: object[] = [
  { stage: "pipeline", status: "running" },
  { stage: "dns", status: "completed", data: { a: ["23.55.142.16"] } },
  { stage: "warm", status: "completed", data: { warmed: true } },
  {
    stage: "sample",
    status: "completed",
    data: [
      { request: 1, http_version: "HTTP/2", status: 200, headers: [["x-cache", "TCP_MISS"]] },
      { request: 2, http_version: "HTTP/2", status: 200, headers: [["x-cache", "TCP_MISS"]] },
    ],
  },
  { stage: "traceroute", status: "completed", data: { hops: [{ n: 1, ip: "10.0.0.1", private: true }] } },
  { stage: "analyze", status: "started" },
];

export function historyRows(n: number): object[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `rep-${i}`,
    url: `https://site${i}.example.com/page`,
    created_at: "2026-07-01T10:00:00Z",
    status: "done",
    provider: "anthropic",
    model: "claude-opus-4-8",
    vantage: "Berlin, DE",
    verdict_json: { cached: true, provider: "Akamai", serving_layer: "Edge", layer_count_to_origin: 2, validation: { ok: true, flags: [] } },
    dns_json: null,
    traceroute_json: null,
    samples_json: null,
    llm_json: { security_findings: [], performance_findings: [{ severity: "critical" }] },
    error: null,
    domain: `site${i}.example.com`,
    has_critical: true,
  }));
}

// A report with very long values (layer names, header values, URL) and ten
// requests — the phone-width layout must wrap it, never scroll sideways.
export function longReport(): object {
  const long = (prefix: string) => `${prefix}-${"x".repeat(120)}`;
  const base = akamaiReport as unknown as { verdict_json: Record<string, unknown>; samples_json: Record<string, unknown>[] };
  const verdict = base.verdict_json as { layers: Record<string, unknown>[] };
  const layers = verdict.layers.map((l) => ({
    ...l,
    layer_name: long("layer"),
    vendor: long("vendor"),
    evidence_headers: [`x-long-header: ${long("value")}`],
  }));
  const sample0 = base.samples_json[0];
  const token = `x-amz-cf-id: ${"Q2xvdWRGcm9udA".repeat(8)}==`;
  const llm = (akamaiReport as unknown as { llm_json: Record<string, unknown> }).llm_json;
  const perf = (llm.performance_findings as Record<string, unknown>[]).map((f) => ({ ...f, description: `${f.description} ${token}` }));
  return {
    ...akamaiReport,
    id: "long",
    llm_json: { ...llm, overall_summary: `${llm.overall_summary} ${token}`, performance_findings: perf },
    url: `https://www.example-foods.com/${"deep/".repeat(30)}page`,
    verdict_json: {
      ...verdict,
      layers,
      serving_layer: layers[2].layer_name,
      confidence_reason: `Lowered because ${token}`,
      timing_check: { status: "consistent", summary: `Timing agrees ${token}`, hidden_layer_suspected: false, confidence: "medium", evidence: [] },
    },
    samples_json: Array.from({ length: 10 }, (_, i) => ({
      ...sample0,
      request: i + 1,
      headers: [["x-long-header", long("value")], ["age", String(i)]],
    })),
  };
}

// 1.3.1: four requests where one changing header carries a long unbroken value
// on request 1 only (a real hackaday.com shape) — it must not squeeze the other
// request columns. 1.3.3: the value is ~1 KB (a kleinanzeigen.de set-cookie
// shape) — the row must clamp instead of growing thousands of pixels tall.
export function changingHeaderReport(): object {
  const base = akamaiReport as unknown as { samples_json: Record<string, unknown>[] };
  const sample0 = base.samples_json[0];
  return {
    ...akamaiReport,
    id: "changing",
    samples_json: [1, 2, 3, 4].map((request) => ({
      ...sample0,
      request,
      timing: { connect_ms: null, tls_ms: null, ttfb_ms: 270.2 + request, total_ms: 300, rtt_ms: request === 1 ? 25.5 : null },
      headers: [
        ["x-cache", request === 1 ? "MISS" : "HIT"],
        ...(request === 1 ? [["set-cookie", `_abck=${"4E163B7FF129ADF23E19699ECB3B2B78~-1~YAAQTUHHF8xlOYShAQAAeQkTmRA7GNq".repeat(16)}; Path=/; Secure`]] : []),
      ],
    })),
  };
}

// ~300 models with one very long name — the launch line must not scroll at 390.
export const LONG_MODELS = {
  providers: [
    {
      id: "openrouter",
      name: "OpenRouter",
      models: [
        { id: "google/gemini-2.5-flash-image-preview", name: "Google: Gemini 2.5 Flash Image Preview (Nano Banana) — extended preview build" },
        ...Array.from({ length: 300 }, (_, i) => ({ id: `m/${i}`, name: `Model ${i}` })),
      ],
    },
  ],
};
