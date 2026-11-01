import type { Report } from "../../api/client";
import { Badge, ConfidenceMeter } from "../../components";
import { confidenceLevel, headlineFor } from "./story";
import type { CacheVerdict } from "./types";
import { isDegraded } from "./types";

// The answer: the verdict in one or two sentences, the model's confidence as
// the page's one loud element, and the "why" paragraph (1.3.0 redesign).
const VALIDATOR_NOTE = "citation check:";
const stripPeriod = (s: string) => s.replace(/[.\s]+$/, "");

function Rerun({ onRerun }: { onRerun?: () => void }) {
  return (
    <button type="button" className="btn-quiet" onClick={onRerun}>
      Re-run
    </button>
  );
}

export function Answer({ report, onRerun }: { report: Report; onRerun?: () => void }) {
  if (report.status === "error") {
    return (
      <div className="answer">
        <h1>
          Analysis failed<span className="answer-detail">{report.error ?? "The run stopped before it finished."}</span>
        </h1>
        <div className="gauge">
          <Rerun onRerun={onRerun} />
        </div>
      </div>
    );
  }
  if (isDegraded(report.verdict_json)) {
    const reason = stripPeriod(String(report.verdict_json?.["reason"] ?? "unknown error"));
    return (
      <div className="answer">
        <h1>
          No verdict<span className="answer-detail">The model couldn't read the evidence: {reason}.</span>
        </h1>
        <div className="gauge">
          <Rerun onRerun={onRerun} />
        </div>
      </div>
    );
  }

  const verdict = report.verdict_json as unknown as CacheVerdict | null;
  if (!verdict) return null;
  const { headline, detail } = headlineFor(verdict);
  const level = confidenceLevel(verdict.confidence);
  const reason = (verdict.confidence_reason ?? "").replace(/^\s*·\s*/, "").trim();
  const summary = (report.llm_json?.["overall_summary"] as string | undefined) ?? "";

  return (
    <>
      <div className="answer">
        <h1>
          {headline}
          {detail && <span className="answer-detail">{detail}</span>}
        </h1>
        <div className="gauge">
          <ConfidenceMeter level={level} size="lg" showWord={false} />
          {level && <span className="gauge-word">{level[0].toUpperCase() + level.slice(1)} confidence</span>}
          {reason && (
            <span className="gauge-reason">
              {reason}
              {reason.includes(VALIDATOR_NOTE) && <Badge variant="unverified" />}
            </span>
          )}
        </div>
      </div>
      {summary && <p className="why">{summary}</p>}
    </>
  );
}
