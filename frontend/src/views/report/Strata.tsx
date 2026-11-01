import { Badge, ConfidenceMeter } from "../../components";
import { classifyLayers, type LayerKind } from "./serving";
import { bandState, layerName, roleLabel } from "./story";
import type { CacheVerdict } from "./types";
import { flagsFor } from "./types";

// The strata (1.3.0): the request's path as stacked bands from "You" down to
// the origin. Band kinds come from classifyLayers — the model's own verdict —
// never from re-reading headers. Replaces the topology chain + layer table.
const KIND_CLASS: Record<LayerKind, string> = {
  served: "served",
  "served-origin": "served-origin",
  passthrough: "passthrough",
  forwards: "forwards",
  unknown: "unknown",
  "not-reached": "unreached",
};

export function Strata({ verdict, vantage }: { verdict: CacheVerdict; vantage: string | null }) {
  const bands = classifyLayers(verdict).layers.filter((c) => c.layer.role !== "client");
  const last = bands[bands.length - 1];
  const originMissing = !last || last.layer.role !== "origin";

  return (
    <div className="strata" aria-label="Cache layers from you to the origin">
      <div className="strata-surface">You, in {vantage || "an unknown location"}</div>
      <ol className="bands">
        {bands.map(({ layer, index, kind }) => {
          const flagged = flagsFor(verdict, `cache_verdict.layers[${index}]`).length > 0;
          return (
            <li key={index} className={`band ${KIND_CLASS[kind]}`}>
              <span className="band-drop" aria-hidden="true" />
              <div className="band-who">
                <div className="band-name">
                  {layerName(layer)}
                </div>
                <div className="band-role">
                  {roleLabel(layer.role)}
                  {layer.location ? `, ${layer.location}` : ""}
                </div>
                {(layer.layer_name !== layerName(layer) || layer.cache_type) && (
                  <div className="band-detail">
                    {[layer.layer_name !== layerName(layer) ? layer.layer_name : null, layer.cache_type]
                      .filter(Boolean)
                      .join(", ")}
                  </div>
                )}
              </div>
              <div className="band-proof">
                <span className={`band-state${kind === "served" ? " hit" : ""}`}>
                  {bandState(kind, layer.role)}
                  {flagged && <Badge variant="unverified" />}
                </span>
                {layer.evidence_headers.map((e, i) => (
                  <code key={i}>{e}</code>
                ))}
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
