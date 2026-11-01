import { Badge, ConfidenceMeter } from "../../components";
import type { CacheVerdict } from "./types";
import { flagsFor } from "./types";

// Two more of the model's claims under the strata, each with its own meter:
// who delivered the page, and whether the timing agrees with the headers.
const TIMING_WORD = {
  consistent: "Agrees with the headers",
  gap: "Doesn't match the headers",
  insufficient: "Not enough timing data",
} as const;

export function Claims({ verdict }: { verdict: CacheVerdict }) {
  const evidence = verdict.provider_evidence?.[0];
  const providerFlagged = flagsFor(verdict, "cache_verdict.provider").length > 0;
  const tc = verdict.timing_check;

  return (
    <div className="claims">
      <div className="claim">
        <span className="claim-k">Delivered by</span>
        <span className="claim-v">
          {verdict.provider}
          {providerFlagged && <Badge variant="unverified" />}
          {evidence && (
            <small>
              {" "}
              from <code>{evidence}</code>
            </small>
          )}
        </span>
        <ConfidenceMeter level={verdict.provider_confidence} />
      </div>
      {tc && (
        <div className={`claim${tc.status === "gap" ? " claim-gap" : ""}`}>
          <span className="claim-k">Timing</span>
          <span className="claim-v">
            <span className="claim-word">{TIMING_WORD[tc.status]}</span>
            {tc.status === "gap" && <Badge variant="timing-gap" />}
            {tc.summary && <small> {tc.summary}</small>}
          </span>
          <ConfidenceMeter level={tc.status === "insufficient" ? null : tc.confidence} />
        </div>
      )}
    </div>
  );
}
