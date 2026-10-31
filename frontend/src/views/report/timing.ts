import type { RawSample } from "./types";

// Timing arithmetic over samples_json — the same rules as the backend bundle
// (app/pipeline/bundle.py timing_section), so the progression table renders
// numbers straight from the samples, never from LLM output.

export function isProbe(s: RawSample): boolean {
  return !!s.probe;
}

export function splitSamples(samples: RawSample[]): { requests: RawSample[]; probe: RawSample | null } {
  return {
    requests: samples.filter((s) => !isProbe(s)),
    probe: samples.find(isProbe) ?? null,
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
