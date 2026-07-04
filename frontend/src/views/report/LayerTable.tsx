import { Badge, Table, TableRow } from "../../components";
import type { BadgeTone } from "../../components";
import type { CacheVerdict } from "./types";
import { classifyLayers, type LayerKind } from "./serving";

// Layer-by-layer breakdown (spec §8 sub-section). Reuses the shared Table
// primitive (variant "layers"); the row for the serving layer gets the
// row-served highlight via TableRow state="served". Every column is a render of
// LLM output — the "Caches this URL?" wording restates the layer's own `caches`
// flag + state, it does not re-derive anything from headers.
const BHV: Record<LayerKind, { tone: BadgeTone; label: string; caches: string }> = {
  served: { tone: "served", label: "SERVED FROM CACHE", caches: "Yes — holds the cached copy" },
  "served-origin": { tone: "origin-serve", label: "GENERATES", caches: "Yes — generates the response" },
  passthrough: { tone: "pass", label: "PASSED THROUGH", caches: "No — forwards upstream" },
  forwards: { tone: "fwd", label: "FORWARDS", caches: "n/a — non-caching layer" },
  "not-reached": { tone: "none", label: "NOT REACHED", caches: "n/a — not reached" },
  unknown: { tone: "unknown", label: "UNKNOWN", caches: "Unknown" },
};

const HEAD = ["Layer", "Cache type", "This request", "Caches this URL?", "Evidence header"];

export function LayerTable({ verdict }: { verdict: CacheVerdict }) {
  const { layers } = classifyLayers(verdict);

  return (
    <Table variant="layers" head={HEAD}>
      <TableRow>
        <td className="layer">
          Browser<span className="hop">client</span>
        </td>
        <td className="type">client</td>
        <td>
          <Badge variant="bhv" tone="init">
            INITIATED
          </Badge>
        </td>
        <td>no — issues the request</td>
        <td className="ev">—</td>
      </TableRow>
      {layers.map(({ layer, kind, index }) => {
        const b = BHV[kind];
        const evidence = layer.evidence_headers[0];
        return (
          <TableRow key={index} state={kind === "served" || kind === "served-origin" ? "served" : undefined}>
            <td className="layer">
              {layer.layer_name}
              <span className="hop">{layer.role.replace(/_/g, " ")}</span>
            </td>
            <td className="type">{layer.cache_type}</td>
            <td>
              <Badge variant="bhv" tone={b.tone}>
                {b.label}
              </Badge>
            </td>
            <td>{b.caches}</td>
            <td className="ev">{evidence ? <code>{evidence}</code> : "—"}</td>
          </TableRow>
        );
      })}
    </Table>
  );
}
