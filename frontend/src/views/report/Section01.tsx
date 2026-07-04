import { Eyebrow } from "../../components";
import type { Report } from "../../api/client";
import { DnsPanel } from "./DnsPanel";
import { Geomap } from "./Geomap";
import { HopLadder } from "./HopLadder";
import { MeasurementSeam } from "./MeasurementSeam";
import { SegmentNarration } from "./SegmentNarration";
import type { CacheVerdict, Dns, Hop, Segment } from "./types";
import { isDegraded } from "./types";

// Section 01 — Network route: DNS panel + geomap, hop ladder, 3-segment
// narration, and the measurement seam. Renders from measured evidence even when
// the verdict is degraded (§8.3: a report never renders empty).
export function Section01({ report }: { report: Report }) {
  const dns = report.dns_json as unknown as Dns | null;
  const traceroute = report.traceroute_json as unknown as { hops?: Hop[] } | null;
  const hops = traceroute?.hops ?? [];
  const verdict = isDegraded(report.verdict_json)
    ? null
    : (report.verdict_json as unknown as CacheVerdict | null);
  const segments = ((report.llm_json?.["segment_narration"] as Segment[] | undefined) ?? []);

  return (
    <>
      <Eyebrow step="01">Network route · DNS &amp; traceroute</Eyebrow>
      <div className="route-grid">
        <DnsPanel dns={dns} verdict={verdict} />
        <Geomap vantage={report.vantage} hops={hops} />
      </div>
      <HopLadder hops={hops} verdict={verdict} />
      <SegmentNarration segments={segments} />
      <MeasurementSeam hops={hops} />
    </>
  );
}
