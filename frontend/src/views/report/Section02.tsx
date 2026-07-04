import { Eyebrow } from "../../components";
import type { Report } from "../../api/client";
import { Findings } from "./Findings";
import { LayerTable } from "./LayerTable";
import { Progression } from "./Progression";
import { RawDrawer } from "./RawDrawer";
import { TopologyChain } from "./TopologyChain";
import type { CacheVerdict, Finding } from "./types";
import { isDegraded } from "./types";

// Section 02 (serving layer) + Section 03 (findings) + raw drawer. Everything
// interpreted — topology, layer table, progression states, findings — hangs off
// the verdict and hides when the report is degraded; the raw-headers drawer is
// measured evidence and always renders (§8.3: never an empty report).
interface Sample {
  request: number;
  http_version?: string;
  status?: number;
  started_at_ms?: number;
  headers: [string, string][];
}

export function Section02({ report }: { report: Report }) {
  const verdict = isDegraded(report.verdict_json)
    ? null
    : (report.verdict_json as unknown as CacheVerdict | null);
  const samples = (report.samples_json as unknown as Sample[] | null) ?? [];
  const security = (report.llm_json?.["security_findings"] as Finding[] | undefined) ?? [];
  const performance = (report.llm_json?.["performance_findings"] as Finding[] | undefined) ?? [];

  return (
    <>
      {verdict && verdict.layers?.length > 0 && (
        <>
          <Eyebrow step="02">Serving layer analysis · from response headers</Eyebrow>
          <TopologyChain verdict={verdict} />

          <Eyebrow sub>Layer-by-layer breakdown</Eyebrow>
          <LayerTable verdict={verdict} />

          {samples.length > 0 && (
            <>
              <Eyebrow sub>Header progression · {samples.length} consecutive requests</Eyebrow>
              <Progression verdict={verdict} samples={samples} />
            </>
          )}

          {(security.length > 0 || performance.length > 0) && (
            <>
              <Eyebrow step="03">Findings · security &amp; performance</Eyebrow>
              <Findings security={security} performance={performance} />
            </>
          )}
        </>
      )}

      <RawDrawer samples={samples} />
    </>
  );
}
