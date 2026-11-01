import { useState } from "react";

import { ConfidenceMeter } from "../../components";
import type { Finding, TimingCheck } from "./types";

// What to look at (1.3.0): security and performance findings as ONE list,
// severity-sorted (critical → warning → info), each with its category, its
// cited evidence, and the model's confidence. A timing gap joins the list as a
// warning, first among warnings; a consistent/insufficient assessment does not
// (1.3.1 — it already reads as the Timing claim row). Beyond the first 5,
// "Show all (N)".
const RANK: Record<Finding["severity"], number> = { critical: 0, warning: 1, info: 2 };
const SEV: Record<Finding["severity"], { cls: string; label: string }> = {
  critical: { cls: "crit", label: "Critical" },
  warning: { cls: "warn", label: "Warning" },
  info: { cls: "info", label: "Info" },
};
const COLLAPSE_AFTER = 5;
export const TIMING_TITLE = "Timing doesn't match the headers";

/** Severity of the timing row, or null when it renders nothing: only a gap is
 *  something to look at. */
export function timingCard(timing: TimingCheck | undefined): Finding["severity"] | null {
  return timing?.status === "gap" ? "warning" : null;
}

interface Row {
  key: string;
  severity: Finding["severity"];
  category: "Security" | "Performance";
  title: string;
  description: string;
  evidence: string[];
  confidence: string | null | undefined;
  absent: boolean; // a bare header name = expected but not present
}

function rows(security: Finding[], performance: Finding[], timing?: TimingCheck): Row[] {
  const fromFinding = (category: Row["category"]) => (f: Finding, i: number): Row => ({
    key: `${category}-${i}`,
    severity: f.severity,
    category,
    title: f.title,
    description: f.description,
    evidence: [f.evidence_header],
    confidence: f.confidence,
    absent: !f.evidence_header.includes(":"),
  });
  const timingSeverity = timingCard(timing);
  const list: Row[] = [
    ...(timing && timingSeverity
      ? [
          {
            key: "timing",
            severity: timingSeverity,
            category: "Performance" as const,
            title: TIMING_TITLE,
            description: timing.summary,
            evidence: timing.evidence,
            confidence: timing.confidence,
            absent: false,
          },
        ]
      : []),
    ...security.map(fromFinding("Security")),
    ...performance.map(fromFinding("Performance")),
  ];
  // Stable sort: the timing row leads its severity group.
  return list.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

export function Findings({
  security,
  performance,
  timing,
}: {
  security: Finding[];
  performance: Finding[];
  timing?: TimingCheck;
}) {
  const [expanded, setExpanded] = useState(false);
  const all = rows(security, performance, timing);
  const visible = expanded ? all : all.slice(0, COLLAPSE_AFTER);

  return (
    <div className="findings">
      {visible.map((r) => {
        const sev = SEV[r.severity] ?? SEV.info;
        return (
          <div key={r.key} className={`finding ${sev.cls}`} data-title={r.title}>
            <div className="finding-sev">
              <span className="sev-word">{sev.label}</span>
              <span className="finding-cat">{r.category}</span>
            </div>
            <div className="finding-body">
              <h3 className="finding-title">{r.title}</h3>
              {r.description && <p>{r.description}</p>}
              {r.evidence.map((e, i) => (
                <code key={i}>{e}</code>
              ))}
              {r.absent && <span className="note"> expected, not present</span>}
            </div>
            <div className="finding-rate">
              <ConfidenceMeter level={r.confidence} />
            </div>
          </div>
        );
      })}
      {all.length > COLLAPSE_AFTER && !expanded && (
        <button type="button" className="btn-quiet show-all" onClick={() => setExpanded(true)}>
          Show all ({all.length})
        </button>
      )}
    </div>
  );
}
