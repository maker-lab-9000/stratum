// Narrow views over the report JSON columns (backend §5.2/§6 shapes). The Report
// type stores these as loose records; we cast at the read boundary.
export interface Layer {
  layer_name: string;
  vendor: string;
  cache_type: string;
  role: string;
  caches: boolean;
  state: string;
  evidence_headers: string[];
  confidence?: string | null; // 1.3.0 per-claim confidence (absent on older reports)
  location?: string;
}

export interface SampleState {
  request: number;
  state: string;
  evidence_headers: string[];
}

export interface ValidationFlag {
  path: string;
  citation: string;
  reason: string;
}

// 1.2.0 — the LLM's reading of HTTP timing against the header story.
export interface TimingCheck {
  status: "consistent" | "gap" | "insufficient";
  summary: string;
  hidden_layer_suspected: boolean;
  confidence: string;
  evidence: string[];
}

export interface CacheVerdict {
  cached: boolean;
  confidence: string;
  provider: string;
  provider_evidence: string[];
  serving_layer: string;
  layer_count_to_origin: number;
  layers: Layer[];
  sample_states: SampleState[];
  validation?: { ok: boolean; flags: ValidationFlag[] };
  confidence_reason?: string; // 1.2.0; absent on older reports
  headline?: string; // 1.3.0
  headline_detail?: string; // 1.3.0
  provider_confidence?: string | null; // 1.3.0
  timing_check?: TimingCheck; // 1.2.0; absent on older reports
  status?: string; // "unavailable" when degraded
  reason?: string;
}

export interface Segment {
  segment: string;
  hop_range: string;
  description: string;
  corroboration: string;
}

export interface Finding {
  severity: "critical" | "warning" | "info";
  title: string;
  description: string;
  evidence_header: string;
  confidence?: string | null; // 1.3.0
}

export interface Hop {
  n: number;
  ip: string | null;
  rdns: string | null;
  asn: number | string | null;
  org: string | null;
  city: string | null;
  rtt_ms: number | null;
  private: boolean;
  unresponsive: boolean;
  hint: string | null;
}

// Route vs samples: did the traceroute end at the IP the samples connected to?
export interface Seam {
  status: "confirmed" | "different_edge" | "unconfirmed";
  traced_ip: string | null;
  peer_ips: string[];
}

export interface SampleTiming {
  connect_ms: number | null;
  tls_ms: number | null;
  ttfb_ms: number | null;
  total_ms: number | null;
  rtt_ms?: number | null; // bare TCP connect to the peer IP (request 1 only)
}

// One entry of samples_json. `probe` marks the cache-bust probe (not one of
// the N requests); `timing`/`peer_ip` are absent on reports before 1.2.0.
export interface RawSample {
  request: number;
  http_version?: string;
  status?: number;
  started_at_ms?: number;
  headers: [string, string][];
  probe?: string;
  peer_ip?: string | null;
  timing?: SampleTiming;
}

export interface Dns {
  a: string[];
  aaaa: string[];
  cname_chain: { name: string; cname: string; ttl: number | null }[];
  ns: string[];
  ttl: number | null;
  truncated?: boolean;
  error?: unknown;
}

export function isDegraded(verdict: Record<string, unknown> | null): boolean {
  return !!verdict && verdict["status"] === "unavailable";
}

export function flagsFor(verdict: CacheVerdict | null, pathPrefix: string): ValidationFlag[] {
  const flags = verdict?.validation?.flags ?? [];
  return flags.filter((f) => f.path.startsWith(pathPrefix));
}
