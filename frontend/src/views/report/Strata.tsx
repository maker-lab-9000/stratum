import { Badge, ConfidenceMeter } from "../../components";
import { classifyLayers, type LayerKind } from "./serving";
import { bandDetail, bandNames, bandState, roleLabel } from "./story";
import { edgeRttMs, formatServerMs, serverMs, splitSamples } from "./timing";
import type { CacheVerdict, RawSample } from "./types";
import { flagsFor } from "./types";

// The strata (1.3.0): the request's path as stacked bands from "You" down to
// the origin. Band kinds come from classifyLayers — the model's own verdict —
// never from re-reading headers. Replaces the topology chain + layer table.
// 1.3.1: bands sharing a vendor are named by layer; the origin band carries one
// measured line — the cache-bust request's time behind the edge (a sample fact).
const KIND_CLASS: Record<LayerKind, string> = {
  served: "served",
  "served-origin": "served-origin",
  passthrough: "passthrough",
  forwards: "forwards",
  unknown: "unknown",
  "not-reached": "unreached",
};

export function Strata({
  verdict,
  vantage,
  samples = [],
}: {
  verdict: CacheVerdict;
  vantage: string | null;
  samples?: RawSample[];
}) {
  const bands = classifyLayers(verdict).layers.filter((c) => c.layer.role !== "client");
  const names = bandNames(bands.map((b) => b.layer));
  const last = bands[bands.length - 1];
  const originMissing = !last || last.layer.role !== "origin";
  const { requests, probe } = splitSamples(samples);
  const probeBehindEdge = probe ? serverMs(probe, edgeRttMs(requests)) : null;

  return (
    <div className="strata" aria-label="Cache layers from you to the origin">
      <div className="strata-surface">You, in {vantage || "an unknown location"}</div>
      <ol className="bands">
        {bands.map(({ layer, index, kind }, i) => {
          const flagged = flagsFor(verdict, `cache_verdict.layers[${index}]`).length > 0;
          const name = names[i];
          const detail = bandDetail(layer, name);
          return (
            <li key={index} className={`band ${KIND_CLASS[kind]}`}>
              <span className="band-drop" aria-hidden="true" />
              <div className="band-who">
                <div className="band-name">{name}</div>
                <div className="band-role">
                  {roleLabel(layer.role)}
                  {layer.location ? `, ${layer.location}` : ""}
                </div>
                {detail && <div className="band-detail">{detail}</div>}
              </div>
              <div className="band-proof">
                <span className={`band-state${kind === "served" ? " hit" : ""}`}>
                  {bandState(kind, layer.role)}
                  {flagged && <Badge variant="unverified" />}
                </span>
                {layer.evidence_headers.map((e, j) => (
                  <code key={j}>{e}</code>
                ))}
                {layer.role === "origin" && probeBehindEdge !== null && (
                  <span className="band-measured">
                    Cache-bust request: {formatServerMs(probeBehindEdge)} behind the edge
                  </span>
                )}
              </div>
              <div className="band-rate">
                <ConfidenceMeter level={layer.confidence} />
              </div>
            </li>
          );
        })}
      </ol>
      {typeof verdict.layer_count_to_origin === "number" && (
        <p className="note strata-count">
          {verdict.layer_count_to_origin} caching {verdict.layer_count_to_origin === 1 ? "layer" : "layers"} between
          you and the origin, by the model's count.
        </p>
      )}
      {originMissing && <p className="note">The model didn't list the origin layer.</p>}
    </div>
  );
}
