import type { CacheVerdict, Layer } from "./types";

// The serving-layer rule (spec §4.2) is applied by the LLM; the frontend only
// *renders* its decision. We map each layer to a presentation kind purely from
// LLM output (state, caches, role, serving_layer) — never by re-reading headers
// (that would be interpreting hit/miss in code, forbidden by §2).
export type LayerKind =
  | "served" // first hit — served from cache (green)
  | "served-origin" // nothing cached, origin generates (blue)
  | "passthrough" // caching layer that missed and forwarded upstream (amber)
  | "forwards" // non-caching layer doing its job — WAF/LB (neutral)
  | "not-reached" // beyond the serving boundary (dimmed)
  | "unknown"; // evidence ambiguous / citation unverifiable (dashed grey)

export interface ClassifiedLayer {
  layer: Layer;
  index: number;
  kind: LayerKind;
}

export interface Classification {
  layers: ClassifiedLayer[];
  servingIndex: number; // -1 when no layer serves
  hasBoundary: boolean; // a "not reached" layer exists past the serving node
}

// Locate the serving layer: prefer the LLM's named serving_layer, else the
// first layer reporting a HIT (the ordering rule's fallback).
function findServingIndex(verdict: CacheVerdict): number {
  const byName = verdict.layers.findIndex(
    (l) => l.layer_name && l.layer_name === verdict.serving_layer,
  );
  if (byName >= 0) return byName;
  return verdict.layers.findIndex((l) => l.state === "HIT");
}

export function classifyLayers(verdict: CacheVerdict): Classification {
  const servingIndex = findServingIndex(verdict);
  const layers: ClassifiedLayer[] = verdict.layers.map((layer, index) => {
    let kind: LayerKind;
    if (index === servingIndex) {
      // The serving node wins regardless of anything else.
      kind = layer.role === "origin" ? "served-origin" : "served";
    } else if (servingIndex >= 0 && index > servingIndex) {
      // Beyond the boundary the layer is never contacted — "not reached" even if
      // its own state came back UNKNOWN (we couldn't observe what we never hit).
      kind = "not-reached";
    } else if (layer.state === "UNKNOWN") {
      kind = "unknown";
    } else if (!layer.caches) {
      kind = "forwards";
    } else {
      kind = "passthrough";
    }
    return { layer, index, kind };
  });
  const hasBoundary =
    servingIndex >= 0 &&
    layers.some((l) => l.index > servingIndex && l.kind === "not-reached");
  return { layers, servingIndex, hasBoundary };
}
