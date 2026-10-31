import { Badge, ConfBar } from "../../components";
import type { CacheVerdict } from "./types";

// Headline verdict confidence (layout "C", operator decision 1.2.0): one line
// above the verdict tiles with the LLM's confidence, a bar, and — when given —
// the reason it isn't high. Notes appended by the citation check carry an
// "unverified" badge. Replaces the confidence bar that used to sit on the
// Cached tile. Hidden for degraded reports (the degraded banner covers them).
export const CONF_PERCENT: Record<string, number> = { high: 92, medium: 66, low: 33 };

const VALIDATOR_NOTE = "citation check:";

const capitalise = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function VerdictConfidence({ verdict }: { verdict: CacheVerdict | null }) {
  if (!verdict) return null;
  const level = verdict.confidence ?? "low";
  const reason = (verdict.confidence_reason ?? "").replace(/^\s*·\s*/, "").trim();
  return (
    <div className="verdict-conf">
      <span className="k">Verdict confidence</span>
      <span className="lvl">{capitalise(level)}</span>
      <ConfBar percent={CONF_PERCENT[level] ?? 33} row={false} />
      {reason && (
        <span className="conf-reason">
          {reason}
          {reason.includes(VALIDATOR_NOTE) && <Badge variant="unverified" />}
        </span>
      )}
    </div>
  );
}
