import type { Report } from "../../api/client";
import { DnsPanel } from "./DnsPanel";
import { Geomap } from "./Geomap";
import { HopLadder } from "./HopLadder";
import { RawDrawer } from "./RawDrawer";
import { SegmentNarration } from "./SegmentNarration";
import { splitSamples } from "./timing";
import type { CacheVerdict, Dns, Hop, RawSample, Seam, Segment } from "./types";
import { isDegraded } from "./types";

// Where it's hosted (1.3.0): the network side of the story, summarised in three
// facts, with the map / hop list and the raw headers folded away. Always shows
// the vantage (§10). The old measurement-seam graphic lives on as one sentence.
function seamText(seam: Seam | undefined): string {
  const peers = seam?.peer_ips.join(", ") || "unknown";
  if (seam?.status === "different_edge") {
    return (
      `The route reached ${seam.traced_ip}, another server for this hostname; the requests ` +
      `connected to ${peers}. The hops describe a sibling edge, not the one that answered.`
    );
  }
  if (seam?.status === "unconfirmed") {
    return (
      `The trace didn't reach the server that answered (${peers}), so the link between the ` +
      "route and the requests is inferred, not measured."
    );
  }
  return (
    "The route ends here: this server terminates the connection, so a trace can't see the cache " +
    "layers behind it. It is the same node that answered the requests."
  );
}

// 1.3.1: the edge's location by the model's reading of the response headers
// (PoP / datacenter tokens) beats GeoIP for anycast addresses. Code compares the
// two strings only; it never parses a header.
function locationConflict(headerLocation: string, geoCity: string | null | undefined): boolean {
  const a = headerLocation.trim().toLowerCase();
  const b = (geoCity ?? "").trim().toLowerCase();
  return !!a && !!b && !a.includes(b) && !b.includes(a);
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function Hosted({ report }: { report: Report }) {
  const dns = report.dns_json as unknown as Dns | null;
  const traceroute = report.traceroute_json as unknown as {
    hops?: Hop[];
    seam?: Seam;
    error?: { message?: string } | null;
  } | null;
  const hops = traceroute?.hops ?? [];
  const samples = (report.samples_json as unknown as RawSample[] | null) ?? [];
  const verdict = isDegraded(report.verdict_json) ? null : (report.verdict_json as unknown as CacheVerdict | null);
  const segments = (report.llm_json?.["segment_narration"] as Segment[] | undefined) ?? [];

  const chain = dns?.cname_chain ?? [];
  const queried = chain[0]?.name ?? hostname(report.url);
  const finalTarget = chain.length ? chain[chain.length - 1].cname : null;
  const responsive = hops.filter((h) => !h.unresponsive);
  const edge = [...responsive].reverse().find((h) => !h.private && h.ip);
  const peer = splitSamples(samples).requests.find((s) => s.peer_ip)?.peer_ip;
  const answered = peer ?? edge?.ip ?? dns?.a?.[0] ?? null;
  const edgeLayer = verdict?.layers?.find((l) => l.role !== "client");
  const headerLocation = (edgeLayer?.location ?? "").trim();
  const conflict = locationConflict(headerLocation, edge?.city);
  const rtt = edge?.rtt_ms != null ? `, ${Math.round(edge.rtt_ms)}\u00a0ms` : "";
  const ending = conflict ? `, ending at ${headerLocation}` : edge?.city ? `, ending in ${edge.city}` : "";

  return (
    <section className="hosted">
      <h2>Where it's hosted</h2>
      <p className="lede">Measured from {report.vantage || "an unknown location"}</p>
      <p className="note">
        The path from this machine to the first server that answered. A trace stops there, so it never
        shows the cache layers above.
      </p>
      <dl className="hosted-grid">
        <div>
          <dt>DNS</dt>
          <dd>
            <code>{queried}</code>
            {finalTarget && <code>{finalTarget}</code>}
          </dd>
        </div>
        <div>
          <dt>Answered by</dt>
          <dd>
            <code>{answered ?? "—"}</code>
            {hops.length > 0 && <span className="note">{seamText(traceroute?.seam)}</span>}
          </dd>
        </div>
        <div>
          <dt>Route</dt>
          <dd>
            {hops.length > 0 ? (
              <>
                {`${responsive.length} ${responsive.length === 1 ? "hop" : "hops"}${ending}${rtt}`}
                {conflict && (
                  <span className="note">
                    {" "}
                    Location from the response headers, by the model's reading. GeoIP says {edge?.city}, which is
                    often wrong for anycast addresses.
                  </span>
                )}
              </>
            ) : (
              <>
                Not traced
                {traceroute?.error?.message && <span className="note"> {traceroute.error.message}</span>}
              </>
            )}
          </dd>
        </div>
      </dl>
      <details className="hosted-more">
        <summary>Map and hop list</summary>
        <div className="route-grid">
          <DnsPanel dns={dns} verdict={verdict} />
          <Geomap vantage={report.vantage} hops={hops} />
        </div>
        <HopLadder hops={hops} verdict={verdict} />
        <SegmentNarration segments={segments} />
      </details>
      <RawDrawer samples={samples} />
    </section>
  );
}
