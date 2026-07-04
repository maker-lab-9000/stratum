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

export const akamaiReport: Report = {
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
