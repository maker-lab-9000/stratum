import { classifyLayers, type LayerKind } from "./serving";
import type { CacheVerdict } from "./types";

// Pure presentation helpers for the story-first report (1.3.0). Everything is
// read from the model's own verdict fields — never from headers — so no vendor
// logic lives in code.

export type ConfidenceLevel = "high" | "medium" | "low";

export function confidenceLevel(v: unknown): ConfidenceLevel | null {
  return v === "high" || v === "medium" || v === "low" ? v : null;
}

/** The model's headline, else a sentence built from the verdict fields. */
export function headlineFor(verdict: CacheVerdict): { headline: string; detail: string } {
  if (verdict.headline) return { headline: verdict.headline, detail: verdict.headline_detail ?? "" };
  if (verdict.cached) return { headline: `Served from ${verdict.serving_layer}.`, detail: "" };
  return { headline: "Not cached. The origin served it.", detail: "" };
}

/** Display name for a layer: its vendor, unless the model left it empty or
 *  "unknown" — then the model's own layer name. */
export function layerName(layer: { vendor?: string; layer_name?: string }): string {
  const vendor = (layer.vendor ?? "").trim();
  if (vendor && vendor.toLowerCase() !== "unknown") return vendor;
  return layer.layer_name || "Unknown";
}
const nameOf = layerName;

/** A few words for lists: "Fastly, behind Amazon CloudFront", "Origin", "No verdict". */
export function servedPhrase(verdict: CacheVerdict | null, degraded: boolean): string {
  if (degraded || !verdict) return "No verdict";
  if (!Array.isArray(verdict.layers)) {
    return verdict.cached ? verdict.serving_layer || "Unknown" : "Origin";
  }
  const { servingIndex } = classifyLayers(verdict);
  if (servingIndex < 0) return verdict.cached ? verdict.serving_layer || "Unknown" : "Origin";
  const serving = verdict.layers[servingIndex];
  if (serving.role === "origin") return "Origin";
  const first = verdict.layers.find((l) => l.role !== "client");
  const name = nameOf(serving);
  if (first && first !== serving && first.vendor && first.vendor !== serving.vendor) {
    return `${name}, behind ${first.vendor}`;
  }
  return name;
}

const BAND_STATE: Record<LayerKind, string> = {
  served: "Hit, served the page",
  "served-origin": "Served by the origin, nothing cached",
  passthrough: "Miss, passed the request on",
  forwards: "Forwards without caching",
  unknown: "Unknown",
  "not-reached": "Not reached",
};

export function bandState(kind: LayerKind, role?: string): string {
  if (kind === "served-origin" && role && role !== "origin") return "Served the page, nothing cached";
  return BAND_STATE[kind];
}

const ROLE_LABEL: Record<string, string> = {
  edge: "Edge cache",
  shield: "Shield cache",
  security: "Security layer",
  load_balancer: "Load balancer",
  reverse_proxy: "Reverse proxy",
  app_cache: "App cache",
  origin: "Origin",
  unknown: "Unidentified layer",
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? "Unidentified layer";
}

/** queued / running analyses aren't finished: they link to the live view. */
export function isInProgress(status: string | null | undefined): boolean {
  return status === "queued" || status === "running";
}
