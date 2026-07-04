import type { ReactNode } from "react";

import type { CacheVerdict } from "./types";
import { classifyLayers, type ClassifiedLayer, type LayerKind } from "./serving";
import { RoleIcon } from "./icons";

// Section 02 topology — the user→origin chain with the serving node flagged and
// the serving-boundary divider. Pure render of the LLM's layer classification
// (serving.ts); no header re-interpretation and no hop→layer inference (§2/§4.4).

// Per-kind node modifier class + friendly state label. `served-origin` and
// `served` are the only green/blue "arrival" states; everything else is neutral
// or dimmed per the palette discipline.
const NODE: Record<LayerKind, { cls: string; state: string }> = {
  served: { cls: "served", state: "CACHE HIT" },
  "served-origin": { cls: "served-origin", state: "GENERATES" },
  passthrough: { cls: "passthrough", state: "PASS-THROUGH" },
  forwards: { cls: "fwd", state: "FORWARDS" },
  "not-reached": { cls: "dim", state: "NOT REACHED" },
  unknown: { cls: "unknown", state: "UNKNOWN" },
};

const humanRole = (role: string) => role.replace(/_/g, " ");

// Split "header-name: value" into a bolded name + value; a bare name renders
// alone. Values are plain text nodes (React-escaped) — never dangerouslySet.
function evidence(headers: string[]): ReactNode {
  const first = headers[0];
  if (!first) return null;
  const idx = first.indexOf(":");
  if (idx < 0) return <b>{first}</b>;
  return (
    <>
      <b>{first.slice(0, idx)}</b> {first.slice(idx + 1).trim()}
    </>
  );
}

function ChainNode({ cl }: { cl: ClassifiedLayer }) {
  const { layer, kind } = cl;
  const { cls, state } = NODE[kind];
  // "not reached" origin nodes carry the dashed-accent origin modifier too.
  const originMod = kind === "not-reached" && layer.role === "origin" ? " origin" : "";
  return (
    <div className={`node ${cls}${originMod}`} tabIndex={0}>
      {kind === "served" && <div className="flag">◆ SERVED FROM HERE</div>}
      {kind === "served-origin" && <div className="flag from-origin">◆ SERVED FROM ORIGIN</div>}
      <div className="ico">
        <RoleIcon role={layer.role} />
      </div>
      <div className="nm">{layer.layer_name}</div>
      <div className="role">{humanRole(layer.role)}</div>
      <div className="ctype">{layer.cache_type}</div>
      <div className="state">{state}</div>
      {layer.evidence_headers.length > 0 && <div className="ev">{evidence(layer.evidence_headers)}</div>}
    </div>
  );
}

// Legend entries in user→origin order, rendered only for kinds present (§8.4).
const LEGEND: { kinds: LayerKind[]; color: string; dashed?: boolean; label: string }[] = [
  { kinds: ["served"], color: "var(--hit)", label: "Served from here" },
  { kinds: ["served-origin"], color: "var(--accent)", label: "Served from origin" },
  { kinds: ["passthrough"], color: "var(--miss)", label: "Passed through" },
  { kinds: ["forwards"], color: "var(--mid)", label: "Forwards" },
  { kinds: ["not-reached"], color: "var(--lo)", label: "Not reached" },
  { kinds: ["unknown"], color: "transparent", dashed: true, label: "Unknown" },
];

export function TopologyChain({ verdict }: { verdict: CacheVerdict }) {
  const { layers, servingIndex, hasBoundary } = classifyLayers(verdict);
  const present = new Set(layers.map((l) => l.kind));
  const hasOrigin = verdict.layers.some((l) => l.role === "origin");

  const legend = LEGEND.filter((e) => e.kinds.some((k) => present.has(k)));
  if (hasOrigin && !present.has("served-origin"))
    legend.push({ kinds: [], color: "var(--accent)", label: "Origin" });

  // Build the flat flex row: browser → (link → node)*, with the serving boundary
  // slotted right after the served node.
  const chain: ReactNode[] = [
    <div className="node" key="client">
      <div className="ico">
        <RoleIcon role="client" />
      </div>
      <div className="nm">Browser</div>
      <div className="role">end user</div>
      <div className="ctype">client</div>
    </div>,
  ];
  layers.forEach((cl, i) => {
    if (hasBoundary && i === servingIndex + 1) {
      chain.push(
        <div className="boundary" key="boundary">
          <div className="lbl">serving boundary</div>
          <div className="rule" />
        </div>,
      );
    }
    const dead = servingIndex >= 0 && i > servingIndex;
    chain.push(
      <div className={`link ${dead ? "dead" : "flow"}`} key={`link-${i}`}>
        {i === 0 && <span className="hops2">network route ▲</span>}
      </div>,
    );
    chain.push(<ChainNode cl={cl} key={`node-${cl.index}`} />);
  });

  const serving = layers[servingIndex]?.layer;

  return (
    <div className="topo-card">
      <div className="topo-head">
        <h3>Which layer serves this page?</h3>
        <div className="legend">
          {legend.map((e) => (
            <span key={e.label}>
              <i
                style={{
                  background: e.color,
                  border: e.dashed ? "1px dashed var(--lo)" : undefined,
                }}
              />
              {e.label}
            </span>
          ))}
        </div>
      </div>

      <p className="topo-verdict" data-testid="topo-verdict">
        {serving ? (
          <>
            Served by <b className="served">{serving.layer_name}</b> — the {serving.cache_type}.{" "}
            {hasBoundary
              ? "Everything beyond it is never contacted on a warm request."
              : "It is the last layer in the observed chain."}
          </>
        ) : (
          <span className="warnword">No layer in the chain reports serving this object.</span>
        )}
      </p>

      <div className="chain" data-testid="chain">
        {chain}
      </div>

      <div className="topo-foot">
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        <span>
          Serving-layer rule, applied by the LLM with machine-checked citations: the request descends
          the chain until the first layer reporting a cache hit. Everything beyond that layer is not
          reached on a warm request, and every cited header was verified against the captured samples.
        </span>
      </div>
    </div>
  );
}
