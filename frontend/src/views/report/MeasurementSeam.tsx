import type { Hop, Seam } from "./types";

// The measurement-seam joint (§8.1.3): the edge IP is the one node shared by
// traceroute (above) and header analysis (below). Traceroute terminates here; the
// shield/dispatcher/origin are invisible to the route and only appear in headers.
// 1.2.0: the seam is only claimed as the *same* node when the route's last hop is
// an IP the samples actually connected to (traceroute_json.seam, backend-computed).
function seamText(n: number, seam?: Seam): string {
  const peers = seam?.peer_ips.join(", ") || "unknown";
  if (seam?.status === "different_edge") {
    return (
      `The route reached ${seam.traced_ip}, another server for this hostname; the samples ` +
      `connected to ${peers}. The hops above describe a sibling edge, not the one that served ` +
      "the headers below."
    );
  }
  if (seam?.status === "unconfirmed") {
    return (
      `Hop ${n} is the last hop the trace reached, but it didn't reach the IP that served the ` +
      `samples (${peers}), so this seam is inferred, not measured. The shield, dispatcher and ` +
      "origin only appear in the header analysis below."
    );
  }
  return (
    `Hop ${n} is the measurement seam: the edge terminates the connection, so traceroute can ` +
    "see no further — the shield, dispatcher and origin are invisible to the route and only " +
    "appear in the header analysis below. The edge IP is the same node that opens the " +
    "serving-layer chain."
  );
}

export function MeasurementSeam({ hops, seam }: { hops: Hop[]; seam?: Seam }) {
  const edge = [...hops].reverse().find((h) => !h.unresponsive && !h.private && h.ip);
  if (!edge) return null;
  return (
    <div className="route-seam">
      <div className="seam-glyph">
        <span className="cap">▲ traceroute ends</span>
        <span className="ip">{edge.ip}</span>
        <span className="cap">▼ headers begin</span>
      </div>
      <span className="body">{seamText(edge.n, seam)}</span>
    </div>
  );
}
