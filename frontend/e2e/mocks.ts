import type { Page } from "@playwright/test";

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
