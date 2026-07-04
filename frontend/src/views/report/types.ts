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
