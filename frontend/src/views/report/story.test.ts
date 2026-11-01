import { describe, expect, test } from "vitest";

import { bandState, confidenceLevel, headlineFor, layerName, roleLabel, servedPhrase } from "./story";
import type { CacheVerdict, Layer } from "./types";

const L = (over: Partial<Layer>): Layer => ({
  layer_name: "L",
  vendor: "",
  cache_type: "cache",
  role: "edge",
  caches: true,
  state: "MISS",
  evidence_headers: [],
  ...over,
});

const V = (layers: Layer[], serving: string, over: Partial<CacheVerdict> = {}): CacheVerdict => ({
  cached: true,
  confidence: "high",
  provider: "p",
  provider_evidence: [],
  serving_layer: serving,
  layer_count_to_origin: 1,
  layers,
  sample_states: [],
  ...over,
});

const CF = L({ layer_name: "CloudFront edge", vendor: "Amazon CloudFront", role: "edge" });
const FASTLY = L({ layer_name: "Fastly shared cache", vendor: "Fastly", role: "shield", state: "HIT" });
const ORIGIN = L({ layer_name: "AEM origin", vendor: "Adobe AEM", role: "origin", caches: false, state: "UNKNOWN" });

describe("story helpers", () => {
  test("confidenceLevel", () => {
    expect(confidenceLevel("high")).toBe("high");
    expect(confidenceLevel("moderate")).toBeNull();
    expect(confidenceLevel(undefined)).toBeNull();
  });

  test("headlineFor uses the model's headline, else a constructed fallback", () => {
    expect(headlineFor(V([FASTLY], "Fastly shared cache", { headline: "H", headline_detail: "D" }))).toEqual({
      headline: "H",
      detail: "D",
    });
    expect(headlineFor(V([L({ layer_name: "Apache Dispatcher" })], "Apache Dispatcher"))).toEqual({
      headline: "Served from Apache Dispatcher.",
      detail: "",
    });
    expect(headlineFor(V([ORIGIN], "AEM origin", { cached: false })).headline).toBe(
      "Not cached. The origin served it.",
    );
  });

  test("servedPhrase", () => {
    expect(servedPhrase(V([CF, FASTLY, ORIGIN], "Fastly shared cache"), false)).toBe(
      "Fastly, behind Amazon CloudFront",
    );
    expect(servedPhrase(V([FASTLY, ORIGIN], "Fastly shared cache"), false)).toBe("Fastly");
    expect(servedPhrase(V([CF, ORIGIN], "AEM origin", { cached: false }), false)).toBe("Origin");
    expect(servedPhrase(V([CF], "nobody", { cached: false }), false)).toBe("Origin");
    expect(servedPhrase(V([CF, FASTLY], "Fastly shared cache"), true)).toBe("No verdict");
    expect(servedPhrase(null, false)).toBe("No verdict");
    expect(servedPhrase(V([L({ layer_name: "Edge thing", vendor: "" })], "Edge thing"), false)).toBe("Edge thing");
  });

  test("servedPhrase copes with verdicts that have no layer list (older rows)", () => {
    const legacy = { cached: true, serving_layer: "Akamai Edge" } as unknown as CacheVerdict;
    expect(servedPhrase(legacy, false)).toBe("Akamai Edge");
    expect(servedPhrase({ cached: false, serving_layer: "Origin" } as unknown as CacheVerdict, false)).toBe("Origin");
  });

  test("an 'unknown' vendor falls back to the layer name", () => {
    expect(layerName(L({ layer_name: "Origin (AEM dispatcher)", vendor: "unknown" }))).toBe("Origin (AEM dispatcher)");
    expect(layerName(L({ layer_name: "Edge", vendor: "UNKNOWN" }))).toBe("Edge");
    expect(layerName(L({ layer_name: "Fastly shared cache", vendor: "Fastly" }))).toBe("Fastly");
    expect(servedPhrase(V([L({ layer_name: "Mystery cache", vendor: "unknown", state: "HIT" })], "Mystery cache"), false)).toBe("Mystery cache");
  });

  test("bandState and roleLabel copy", () => {
    expect(bandState("served")).toBe("Hit, served the page");
    expect(bandState("served-origin")).toBe("Served by the origin, nothing cached");
    expect(bandState("passthrough")).toBe("Miss, passed the request on");
    expect(bandState("forwards")).toBe("Forwards without caching");
    expect(bandState("unknown")).toBe("Unknown");
    expect(bandState("not-reached")).toBe("Not reached");
    expect(roleLabel("edge")).toBe("Edge cache");
    expect(roleLabel("shield")).toBe("Shield cache");
    expect(roleLabel("security")).toBe("Security layer");
    expect(roleLabel("load_balancer")).toBe("Load balancer");
    expect(roleLabel("reverse_proxy")).toBe("Reverse proxy");
    expect(roleLabel("app_cache")).toBe("App cache");
    expect(roleLabel("origin")).toBe("Origin");
    expect(roleLabel("unknown")).toBe("Unidentified layer");
    expect(roleLabel("weird")).toBe("Unidentified layer");
  });
});
