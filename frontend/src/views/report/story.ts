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

const meaningfulVendor = (layer: { vendor?: string }) => {
  const v = (layer.vendor ?? "").trim().toLowerCase();
  return v && v !== "unknown" ? v : null;
};

/** Band names for the strata (1.3.1): the vendor, unless two or more bands share
 *  it — then each of those is named by the model's own layer name, so the bands
 *  stay distinguishable (two layer names, not the same vendor twice). */
export function bandNames(layers: { vendor?: string; layer_name?: string }[]): string[] {
  const counts = new Map<string, number>();
  for (const l of layers) {
    const v = meaningfulVendor(l);
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return layers.map((l) => {
    const v = meaningfulVendor(l);
    if (v && (counts.get(v) ?? 0) > 1 && l.layer_name) return l.layer_name;
    return layerName(l);
  });
}

/** The quiet line under a band name: layer name, vendor and cache type, minus
 *  anything the name or an earlier part already says (case-insensitive). */
export function bandDetail(layer: { vendor?: string; layer_name?: string; cache_type?: string }, name: string): string {
  const said = [name.toLowerCase()];
  const parts: string[] = [];
  for (const raw of [layer.layer_name, layer.vendor, layer.cache_type]) {
    const part = (raw ?? "").trim();
    const lower = part.toLowerCase();
    if (!part || lower === "unknown" || said.some((s) => s.includes(lower))) continue;
    parts.push(part);
    said.push(lower);
  }
  return parts.join(", ");
}

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

// Split prose into sentences for the "model's reading" points (1.3.3). Pure
// text handling, no reading of meaning: a sentence ends at . ! or ? followed by
// whitespace and a capital letter, a digit or an opening quote/bracket. A period
// that closes an abbreviation (B.V., i.e., e.g., vs., approx.) or sits inside a
// hostname (www.example.de) never ends a sentence.
const ABBREVIATIONS = new Set(["e.g", "i.e", "vs", "approx", "etc", "cf", "no", "ca", "resp"]);

export function sentences(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  const re = /[.!?]+(?=\s+[A-Z0-9"'(\[])/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const end = m.index + m[0].length;
    const before = text.slice(start, m.index);
    const lastWord = before.split(/\s+/).pop() ?? "";
    // "B.V" / "U.S" style initials, or a listed abbreviation: keep going.
    if (m[0] === "." && (/^(?:[A-Za-z]\.)+[A-Za-z]$/.test(lastWord) || ABBREVIATIONS.has(lastWord.toLowerCase()))) continue;
    const s = text.slice(start, end).trim();
    if (s) out.push(s);
    start = end;
  }
  const tail = text.slice(start).trim();
  if (tail) out.push(tail);
  return out;
}
