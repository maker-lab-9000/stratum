import type { RawSample } from "./types";

// Timing arithmetic over samples_json — the same rules as the backend bundle
// (app/pipeline/bundle.py timing_section), so the progression table renders
// numbers straight from the samples, never from LLM output.

/** The original cache-bust probe (1.4.0: never an investigation request). */
export function isProbe(s: RawSample): boolean {
  return s.probe === "cache_bust";
}

/** A request the model asked for in investigate mode (1.4.0). */
export function isInvestigation(s: RawSample): boolean {
  return s.probe === "investigation";
}

export function splitSamples(samples: RawSample[]): {
  requests: RawSample[];
  probe: RawSample | null;
  investigations: RawSample[];
} {
  return {
    requests: samples.filter((s) => !isProbe(s) && !isInvestigation(s)),
    probe: samples.find(isProbe) ?? null,
    investigations: samples.filter(isInvestigation),
  };
}

const round1 = (x: number) => Math.round(x * 10) / 10;

/** Edge round trip = the sampler's bare TCP connect to the peer IP (rtt_ms).
 *  Never connect_ms: that span includes DNS resolution (same rule as the bundle). */
export function edgeRttMs(requests: RawSample[]): number | null {
  for (const s of requests) {
    const r = s.timing?.rtt_ms;
    if (typeof r === "number") return r;
  }
  return null;
}

/** Time to first byte minus the edge round trip ≈ time spent behind the edge. */
export function serverMs(s: RawSample, edgeRtt: number | null): number | null {
  const ttfb = s.timing?.ttfb_ms;
  if (typeof ttfb !== "number" || edgeRtt === null) return null;
  return round1(ttfb - edgeRtt);
}

/** Server time for display (1.3.1): below 1 ms — including small negatives from
 *  RTT jitter — reads "<1 ms". The exact value stays in the bundle facts. */
export function formatServerMs(v: number | null | undefined): string {
  if (typeof v !== "number") return "—";
  return v < 1 ? "<1 ms" : `${v} ms`;
}
