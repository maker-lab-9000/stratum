import type { Report } from "../api/client";

// The mockup's "CDN bypass" story as a full report (shared by T18/T19 tests and
// the /dev/report demo). Shapes match the backend: dns_json, samples_json,
// traceroute_json (enriched hops), verdict_json (validated cache_verdict +
// validation report), llm_json (StructuredResult).

const HOPS = [
  { n: 1, ip: "10.0.0.1", rdns: "_gateway", asn: null, org: null, city: "Berlin", rtt_ms: 0.4, private: true, unresponsive: false, hint: null },
  { n: 2, ip: "62.155.241.18", rdns: "lo-1.br01.berl.de.net", asn: 3320, org: "Deutsche Telekom", city: "Berlin", rtt_ms: 3.1, private: false, unresponsive: false, hint: null },
  { n: 3, ip: "87.190.12.5", rdns: "f-eb1.berl.de.net", asn: 3320, org: "Deutsche Telekom", city: "Berlin", rtt_ms: 3.4, private: false, unresponsive: false, hint: null },
  { n: 4, ip: "194.25.6.131", rdns: "f-ed4.ffm.de.net", asn: 3320, org: "Deutsche Telekom", city: "Frankfurt", rtt_ms: 5.2, private: false, unresponsive: false, hint: "FRA/Frankfurt" },
  { n: 5, ip: "80.81.193.140", rdns: "akamai.de-cix.frankfurt.net", asn: 6695, org: "DE-CIX", city: "Frankfurt", rtt_ms: 5.6, private: false, unresponsive: false, hint: "FRA/Frankfurt" },
  { n: 6, ip: "23.203.148.9", rdns: "ae12.r01.ffm.akamai.net", asn: 20940, org: "Akamai Technologies", city: "Frankfurt", rtt_ms: 5.9, private: false, unresponsive: false, hint: "FRA/Frankfurt" },
  { n: 7, ip: "23.55.142.16", rdns: "a23-55-142-16.deploy.static.akamaitechnologies.com", asn: 20940, org: "Akamai Technologies", city: "Frankfurt", rtt_ms: 6.1, private: false, unresponsive: false, hint: "FRA/Frankfurt" },
];

function sample(request: number) {
  return {
    request,
    ok: true,
    status: 200,
    http_version: "HTTP/2",
    url: "https://www.example-foods.com/en/recipes/slow-roast-hero",
    headers: [
      ["server", "AkamaiGHost"],
      ["content-type", "text/html; charset=utf-8"],
      ["x-cache", "TCP_MISS from a23-55-142-16.deploy.static.akamaitechnologies.com"],
      ["x-cache-remote", "TCP_MISS from a80-akamai"],
      ["server-timing", "dispatcher;desc=HIT"],
      ["cache-control", "no-store, no-cache, max-age=0"],
      ["age", "0"],
      ["via", "1.1 v1-akamaitech.net (ghost)"],
    ],
    elapsed_ms: 41 + request,
    started_at_ms: (request - 1) * 250,
    error: null,
  };
}

const CACHE_VERDICT = {
  cached: true,
  confidence: "high",
  provider: "Akamai",
  provider_evidence: ["example-foods.com.edgekey.net", "AS20940 Akamai Technologies"],
  serving_layer: "Apache Dispatcher",
  layer_count_to_origin: 3,
  layers: [
    { layer_name: "Akamai Edge", vendor: "Akamai", cache_type: "CDN edge cache", role: "edge", caches: true, state: "PASS", evidence_headers: ["x-cache: TCP_MISS"] },
    { layer_name: "Akamai Shield", vendor: "Akamai", cache_type: "parent cache", role: "shield", caches: true, state: "PASS", evidence_headers: ["x-cache-remote: TCP_MISS"] },
    { layer_name: "Apache Dispatcher", vendor: "Apache / AEM", cache_type: "disk cache", role: "reverse_proxy", caches: true, state: "HIT", evidence_headers: ["server-timing: dispatcher;desc=HIT"] },
    { layer_name: "AEM Publish", vendor: "Adobe AEM", cache_type: "origin app", role: "origin", caches: false, state: "UNKNOWN", evidence_headers: [] },
  ],
  sample_states: [1, 2, 3, 4].map((request) => ({ request, state: "MISS", evidence_headers: ["x-cache: TCP_MISS"] })),
};

const LLM_JSON = {
  cache_verdict: CACHE_VERDICT,
  overall_summary:
    "The page is fronted by Akamai (CNAME chain terminating at akamaiedge.net, Server: AkamaiGHost) but the CDN never stores it — all four requests MISS at both Akamai tiers with Age flat at 0 and Cache-Control: no-store. It is served from the Apache Dispatcher (Server-Timing dispatcher;desc=HIT), the third cache layer.",
  segment_narration: [
    { segment: "Access", hop_range: "hops 1–3", description: "Leaves the vantage on Deutsche Telekom's Berlin metro (AS3320). Standard last-mile; latency under 3.5 ms, no congestion signal.", corroboration: "Origin ISP, not part of the delivery path." },
    { segment: "Transit", hop_range: "hops 4–5", description: "Stays domestic — DTAG carries it to Frankfurt, then hands off at DE-CIX (AS6695). No long-haul transit carrier; the route never leaves Germany.", corroboration: "Peering handoff at DE-CIX Frankfurt." },
    { segment: "CDN network", hop_range: "hops 6–7", description: "Enters AS20940 (Akamai) and terminates at the anycast edge in Frankfurt. This IP is where the connection is served — and where header analysis takes over.", corroboration: "Matches the Via header & edgekey.net CNAME." },
  ],
  security_findings: [
    { severity: "warning", title: "No HSTS header", description: "No Strict-Transport-Security header on any of the four samples; the site does not enforce HTTPS at the browser.", evidence_header: "Strict-Transport-Security" },
    { severity: "info", title: "Server header discloses AkamaiGHost", description: "The Server header names the edge software.", evidence_header: "server: AkamaiGHost" },
  ],
  performance_findings: [
    { severity: "critical", title: "CDN is not caching (full bypass)", description: "Age is flat at 0 and Cache-Control is no-store across every request; the Akamai edge forwards to origin each time, wasting the CDN tier.", evidence_header: "Age: 0" },
    { severity: "warning", title: "Cache-Control forbids storage", description: "no-store on every response prevents any shared cache from retaining the object.", evidence_header: "Cache-Control: no-store, no-cache, max-age=0" },
  ],
};

// 1.3.0 story fields + per-claim confidence (the model's own ratings).
const STORY_VERDICT = {
  ...CACHE_VERDICT,
  headline: "Served from the Apache Dispatcher in Frankfurt.",
  headline_detail: "Both Akamai tiers missed every request.",
  provider_confidence: "high",
  layers: CACHE_VERDICT.layers.map((layer, i) => ({
    ...layer,
    confidence: ["high", "high", "high", "low"][i],
    location: i < 2 ? "Frankfurt" : "",
  })),
};

/** The same report as produced before 1.3.0 (no headline / per-claim fields). */
export const akamaiReportLegacy: Report = {
  id: "akamai-bypass-demo",
  url: "https://www.example-foods.com/en/recipes/slow-roast-hero",
  created_at: "2026-06-26T14:22:00+02:00",
  status: "done",
  provider: "anthropic",
  model: "claude-opus-4-8",
  vantage: "Berlin, DE · Playwright runner",
  verdict_json: { ...CACHE_VERDICT, validation: { ok: true, flags: [] } },
  dns_json: {
    a: ["23.55.142.16"],
    aaaa: ["2a02:26f0:1700::aef"],
    cname_chain: [
      { name: "www.example-foods.com", cname: "example-foods.com", ttl: 300 },
      { name: "example-foods.com", cname: "example-foods.com.edgekey.net", ttl: 300 },
      { name: "example-foods.com.edgekey.net", cname: "e1234.dscx.akamaiedge.net", ttl: 20 },
    ],
    ns: ["a1-64.akam.net", "a5-65.akam.net"],
    ttl: 20,
    truncated: false,
  },
  traceroute_json: { tool: "mtr", target: "e1234.dscx.akamaiedge.net", port: 443, timed_out: false, error: null, hops: HOPS, geo_available: true, enrichment_notes: [] },
  samples_json: [1, 2, 3, 4].map(sample),
  llm_json: LLM_JSON,
  error: null,
  domain: "www.example-foods.com",
  has_critical: true,
};

export const akamaiReport: Report = {
  ...akamaiReportLegacy,
  verdict_json: { ...STORY_VERDICT, validation: { ok: true, flags: [] } },
  llm_json: {
    ...LLM_JSON,
    cache_verdict: STORY_VERDICT,
    security_findings: (LLM_JSON.security_findings as Record<string, unknown>[]).map((f) => ({ ...f, confidence: "medium" })),
    performance_findings: (LLM_JSON.performance_findings as Record<string, unknown>[]).map((f) => ({ ...f, confidence: "high" })),
  },
};

// 1.4.0: the same report after an investigate-mode run — two extra requests,
// the model's account, the pipeline's call log (the third call refused by the
// budget) and two recommendations.
const INVESTIGATION_SAMPLES = [
  {
    ...sample(6),
    probe: "investigation",
    investigation: { n: 1, headers: { "Pragma": "akamai-x-cache-on, akamai-x-get-cache-key" }, cache_bust: false, reason: "Reveal the edge cache state Akamai strips by default." },
    headers: [...sample(6).headers, ["X-Cache", "TCP_MISS from a23-55-142-16.deploy.akamaitechnologies.com (AkamaiGHost/11.4.3) (-)"], ["X-Cache-Key", "/L/1234/567/1d/www.example-foods.com/"]],
  },
  {
    ...sample(7),
    ok: false,
    status: undefined,
    probe: "investigation",
    investigation: { n: 2, headers: { "User-Agent": "Mozilla/5.0 (Android 14; Mobile)" }, cache_bust: false, reason: "Check whether a mobile User-Agent gets a cached variant." },
    headers: [],
    error: "ReadTimeout: timed out",
  },
];

const INVESTIGATION_LOG = [
  {
    n: 1, request: 6, asked_at_ms: 1762034400000, answered_at_ms: 1762034400310,
    model_said: "The edge strips its cache state; Akamai's Pragma debug tokens should reveal it.",
    input: { headers: { "Pragma": "akamai-x-cache-on, akamai-x-get-cache-key" }, cache_bust: false, reason: "Reveal the edge cache state Akamai strips by default." },
    sent: { url: "https://www.example-foods.com/", method: "GET", headers: [["Pragma", "akamai-x-cache-on, akamai-x-get-cache-key"]] },
    response: { status: 200, http_version: "HTTP/2", peer_ip: "23.55.142.16", timing: { connect_ms: null, tls_ms: null, ttfb_ms: 46, total_ms: 52, rtt_ms: null }, header_count: INVESTIGATION_SAMPLES[0].headers.length },
    returned: { request: 6, sample: INVESTIGATION_SAMPLES[0], timing: { request: 6, ttfb_ms: 46, server_ms: 20.5, facts: ["request 6 ttfb_ms: 46", "request 6 server_ms: 20.5"] } },
    refused: null,
  },
  {
    n: 2, request: 7, asked_at_ms: 1762034401500, answered_at_ms: 1762034411500,
    model_said: "",
    input: { headers: { "User-Agent": "Mozilla/5.0 (Android 14; Mobile)" }, reason: "Check whether a mobile User-Agent gets a cached variant." },
    sent: { url: "https://www.example-foods.com/", method: "GET", headers: [["User-Agent", "Mozilla/5.0 (Android 14; Mobile)"]] },
    response: { error: "ReadTimeout: timed out" },
    returned: { request: 7, sample: INVESTIGATION_SAMPLES[1], timing: { request: 7, ttfb_ms: null, server_ms: null, facts: [] } },
    refused: null,
  },
  {
    n: 3, request: null, asked_at_ms: 1762034412000, answered_at_ms: 1762034412001,
    model_said: "Let me retry the mobile request once more.",
    input: { headers: { "User-Agent": "Mozilla/5.0 (Android 14; Mobile)" }, reason: "Retry the timed-out mobile request." },
    sent: null, response: null,
    returned: { error: "request refused: header 'Host' cannot be set" },
    refused: "header_policy: header 'Host' cannot be set",
  },
];

export const investigatedReport: Report = {
  ...akamaiReport,
  id: "investigated",
  samples_json: [...(akamaiReport.samples_json as unknown[]), ...INVESTIGATION_SAMPLES],
  llm_json: {
    ...(akamaiReport.llm_json as Record<string, unknown>),
    investigation: {
      summary: "Akamai's debug tokens confirmed the edge misses; the mobile variant check timed out.",
      steps: [
        { request: 6, purpose: "Reveal the edge cache state Akamai strips by default.", observed: "X-Cache: TCP_MISS from the edge, so the miss is confirmed, and the cache key shows the plain URL." },
        { request: 7, purpose: "Check whether a mobile User-Agent gets a cached variant.", observed: "No response within the timeout; nothing learned." },
      ],
    },
    investigation_log: INVESTIGATION_LOG,
    recommendations: [
      { action: "Run the analysis from another region", reason: "Akamai's anycast edge may hold a different copy per PoP; a second vantage would show whether the miss is local.", confidence: "medium" },
      { action: "Retry the mobile User-Agent request", reason: "The only variant check timed out, so the Vary question is still open." },
    ],
    usage: { input_tokens: 48210, output_tokens: 2140 },
  },
};
