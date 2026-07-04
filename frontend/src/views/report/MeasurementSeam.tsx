import type { Hop } from "./types";

// The measurement-seam joint (§8.1.3): the edge IP is the one node shared by
// traceroute (above) and header analysis (below). Traceroute terminates here; the
// shield/dispatcher/origin are invisible to the route and only appear in headers.
export function MeasurementSeam({ hops }: { hops: Hop[] }) {
  const edge = [...hops].reverse().find((h) => !h.unresponsive && !h.private && h.ip);
  if (!edge) return null;
  return (
    <div className="route-seam">
      <div className="seam-glyph">
        <span className="cap">▲ traceroute ends</span>
        <span className="ip">{edge.ip}</span>
        <span className="cap">▼ headers begin</span>
      </div>
      <span className="body">
        Hop {edge.n} is the measurement seam: the edge terminates the connection, so
        traceroute can see no further — the shield, dispatcher and origin are invisible to
        the route and only appear in the header analysis below. The edge IP is the same node
        that opens the serving-layer chain.
      </span>
    </div>
  );
}
