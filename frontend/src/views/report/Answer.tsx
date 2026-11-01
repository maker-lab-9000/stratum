import type { Report } from "../../api/client";
import { Badge, ConfidenceMeter } from "../../components";
import { confidenceLevel, headlineFor, sentences } from "./story";
import type { CacheVerdict } from "./types";
import { isDegraded } from "./types";

// The answer: the verdict in one or two sentences, the model's confidence as
// the page's one loud element, and the "why" paragraph (1.3.0 redesign).
const VALIDATOR_NOTE = "citation check:";
const stripPeriod = (s: string) => s.replace(/[.\s]+$/, "");

// Reasoning (1.3.3): the model's overall_summary, ordered by the prompt from
// the request outward to the origin, ending with the confidence sentence. One
// or two sentences read as a paragraph; three or more as one point per
// sentence, and a last point about confidence is set bold. The words are the
// model's, verbatim.
const POINTS_FROM = 3;
const CONFIDENCE_LINE = /\bconfidence\b/i;
function Summary({ text }: { text: string }) {
  const parts = sentences(text);
  const body =
    parts.length < POINTS_FROM ? (
      <p className="why">{text}</p>
    ) : (
      <ul className="why">
        {parts.map((s, i) => {
          const last = i === parts.length - 1;
          return <li key={i}>{last && CONFIDENCE_LINE.test(s) ? <strong>{s}</strong> : s}</li>;
        })}
      </ul>
    );
  return (
    <section className="reasoning">
      <h2>Reasoning</h2>
      {body}
    </section>
  );
}

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
      {summary && <Summary text={summary} />}
    </>
  );
}
