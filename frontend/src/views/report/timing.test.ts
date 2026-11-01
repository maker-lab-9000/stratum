import { describe, expect, test } from "vitest";

import { edgeRttMs, formatServerMs, isInvestigation, isProbe, serverMs, splitSamples } from "./timing";
import type { RawSample, SampleTiming } from "./types";

const timing = (t: Partial<SampleTiming>): SampleTiming => ({
  connect_ms: null,
  tls_ms: null,
  ttfb_ms: null,
  total_ms: null,
  rtt_ms: null,
  ...t,
});

const sample = (request: number, extra: Partial<RawSample> = {}): RawSample => ({
  request,
  headers: [],
  ...extra,
});

describe("timing helpers", () => {
  test("splits probe from requests", () => {
    const probe = sample(4, { probe: "cache_bust" });
    const { requests, probe: found } = splitSamples([sample(1), sample(2), sample(3), probe]);
    expect(requests).toHaveLength(3);
    expect(found?.request).toBe(4);
    expect(isProbe(probe)).toBe(true);
    expect(splitSamples([sample(1)]).probe).toBeNull();
  });

  test("isProbe is only the cache-bust probe; investigation samples are split out", () => {
    // 1.4.0 (Review Focus 3): with no cache-bust probe and an investigation
    // request that busts the cache, "the probe" stays null.
    const inv = sample(5, { probe: "investigation", investigation: { n: 1, headers: { "X-Debug": "1" }, cache_bust: true, reason: "r" } });
    expect(isProbe(inv)).toBe(false);
    expect(isInvestigation(inv)).toBe(true);
    const split = splitSamples([sample(1), sample(2), inv]);
    expect(split.requests.map((s) => s.request)).toEqual([1, 2]);
    expect(split.probe).toBeNull();
    expect(split.investigations.map((s) => s.request)).toEqual([5]);
    // The original probe is still found when present.
    expect(splitSamples([sample(1), sample(4, { probe: "cache_bust" }), inv]).probe?.request).toBe(4);
  });

  test("edge rtt is the first bare-TCP rtt_ms, never the DNS-inclusive connect_ms", () => {
    const reqs = [
      sample(1, { timing: timing({ connect_ms: 87.5 }) }),
      sample(2, { timing: timing({ connect_ms: 95, rtt_ms: 38.2 }) }),
      sample(3, { timing: timing({ rtt_ms: 40 }) }),
    ];
    expect(edgeRttMs(reqs)).toBe(38.2);
    expect(edgeRttMs([sample(1, { timing: timing({ connect_ms: 87.5 }) })])).toBeNull();
    expect(edgeRttMs([sample(1)])).toBeNull();
  });

  test("server time matches bundle arithmetic", () => {
    expect(serverMs(sample(2, { timing: timing({ ttfb_ms: 41.4 }) }), 38.2)).toBe(3.2);
    expect(serverMs(sample(2, { timing: timing({ ttfb_ms: null }) }), 38.2)).toBeNull();
    expect(serverMs(sample(2, { timing: timing({ ttfb_ms: 41.4 }) }), null)).toBeNull();
    expect(serverMs(sample(2), 38.2)).toBeNull();
  });

  test("server time below 1 ms (or negative, from jitter) reads <1 ms", () => {
    expect(formatServerMs(-1.3)).toBe("<1 ms");
    expect(formatServerMs(0.5)).toBe("<1 ms");
    expect(formatServerMs(0)).toBe("<1 ms");
    expect(formatServerMs(1)).toBe("1 ms");
    expect(formatServerMs(250)).toBe("250 ms");
    expect(formatServerMs(null)).toBe("—");
  });
});
