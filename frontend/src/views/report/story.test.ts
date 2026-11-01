import { describe, expect, test } from "vitest";

import { bandDetail, bandNames, bandState, confidenceLevel, headlineFor, layerName, roleLabel, sentences, servedPhrase } from "./story";
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

// --- 1.3.1: band names when bands share a vendor; no repeated detail ----------

describe("band names", () => {
  test("bands that share a vendor are named by the model's layer name", () => {
    const layers = [
      L({ layer_name: "Akamai Edge", vendor: "Akamai", role: "edge" }),
      L({ layer_name: "Akamai Shield", vendor: "Akamai", role: "shield" }),
      L({ layer_name: "Apache Dispatcher", vendor: "Apache / AEM", role: "reverse_proxy" }),
    ];
    expect(bandNames(layers)).toEqual(["Akamai Edge", "Akamai Shield", "Apache / AEM"]);
  });

  test("vendor matching ignores case and unknown vendors never count as shared", () => {
    const layers = [
      L({ layer_name: "WordPress VIP edge cache", vendor: "Automattic" }),
      L({ layer_name: "WordPress origin", vendor: "automattic ", role: "origin" }),
      L({ layer_name: "Mystery A", vendor: "unknown" }),
      L({ layer_name: "Mystery B", vendor: "unknown" }),
    ];
    expect(bandNames(layers)).toEqual(["WordPress VIP edge cache", "WordPress origin", "Mystery A", "Mystery B"]);
  });

  test("detail drops anything the name or an earlier part already says", () => {
    const edge = L({ layer_name: "Akamai Edge", vendor: "Akamai", cache_type: "CDN edge cache" });
    expect(bandDetail(edge, "Akamai Edge")).toBe("CDN edge cache");
    const wp = L({ layer_name: "WordPress VIP edge cache", vendor: "Automattic", cache_type: "edge cache" });
    expect(bandDetail(wp, "WordPress VIP edge cache")).toBe("Automattic");
    const varnish = L({ layer_name: "Varnish app cache", vendor: "Varnish", cache_type: "App cache" });
    expect(bandDetail(varnish, "Varnish")).toBe("Varnish app cache");
    const dispatcher = L({ layer_name: "Apache Dispatcher", vendor: "Apache / AEM", cache_type: "disk cache" });
    expect(bandDetail(dispatcher, "Apache / AEM")).toBe("Apache Dispatcher, disk cache");
    expect(bandDetail(L({ layer_name: "Origin", vendor: "unknown", cache_type: "" }), "Origin")).toBe("");
  });
});

describe("sentences", () => {
  test("splits prose on sentence ends, keeping abbreviations and hostnames whole", () => {
    const text =
      "DNS and the network path point to Akamai. The CNAME chain runs www.kleinanzeigen.de -> edgekey.net -> akamaiedge.net, " +
      "and the answering IP sits in AS20940 Akamai International B.V. (Berlin). Akamai's hit/miss headers are stripped. " +
      "Server time stays around 130-170 ms, which fits an origin trip (i.e. no stored copy). Confidence is medium because the headers are hidden.";
    expect(sentences(text)).toEqual([
      "DNS and the network path point to Akamai.",
      "The CNAME chain runs www.kleinanzeigen.de -> edgekey.net -> akamaiedge.net, and the answering IP sits in AS20940 Akamai International B.V. (Berlin).",
      "Akamai's hit/miss headers are stripped.",
      "Server time stays around 130-170 ms, which fits an origin trip (i.e. no stored copy).",
      "Confidence is medium because the headers are hidden.",
    ]);
  });

  test("handles question and exclamation ends, and empty input", () => {
    expect(sentences("Is it cached? No! It is not.")).toEqual(["Is it cached?", "No!", "It is not."]);
    expect(sentences("")).toEqual([]);
    expect(sentences("One sentence without a period")).toEqual(["One sentence without a period"]);
  });
});
