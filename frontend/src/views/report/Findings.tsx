import { useState } from "react";

import { Badge } from "../../components";
import type { BadgeTone } from "../../components";
import type { Finding, TimingCheck } from "./types";

// Section 03 findings — Security and Performance columns. Severity-sorted
// (critical → warning → info); beyond the top 3 per column the rest collapse
// behind a "show all (N)" control (§8.4). Amber is reserved for warnings; a raw
// MISS is never dressed as a finding here.
const RANK: Record<Finding["severity"], number> = { critical: 0, warning: 1, info: 2 };
const SEV: Record<Finding["severity"], { tone: BadgeTone; label: string }> = {
  critical: { tone: "crit", label: "Critical" },
  warning: { tone: "warn", label: "Warning" },
  info: { tone: "info", label: "Info" },
};
const CARD: Record<Finding["severity"], string> = { critical: "crit", warning: "warn", info: "info" };
const COLLAPSE_AFTER = 3;

function countLabel(findings: Finding[]): string {
  const parts: string[] = [];
  for (const sev of ["critical", "warning", "info"] as const) {
    const c = findings.filter((f) => f.severity === sev).length;
    if (c) parts.push(`${c} ${sev}`);
  }
  return parts.length ? `· ${parts.join(" · ")}` : "· none";
}

function FindingCard({ f }: { f: Finding }) {
  const sev = SEV[f.severity] ?? SEV.info;
  // A bare header name (no value) reads as an expected-but-absent header.
  const present = f.evidence_header.includes(":");
  return (
    <div className={`card ${CARD[f.severity] ?? "info"}`}>
      <div className="row1">
        <Badge variant="sev" tone={sev.tone}>
          {sev.label}
        </Badge>
        <span className="ttl">{f.title}</span>
      </div>
      <p>{f.description}</p>
      <div className="hdr-lbl">{present ? "Response header" : "Expected, not present"}</div>
      <code>{f.evidence_header}</code>
    </div>
  );
}

// 1.2.0 — the LLM's timing assessment as a Performance card: a gap is a
// warning (first among warnings); a consistent/insufficient note with a summary
// is info; anything else renders nothing.
export const TIMING_TITLE = "Timing doesn't match the headers";

export function timingCard(timing: TimingCheck | undefined): Finding["severity"] | null {
  if (!timing) return null;
  if (timing.status === "gap") return "warning";
  return timing.summary ? "info" : null;
}

function TimingCard({ timing, severity }: { timing: TimingCheck; severity: Finding["severity"] }) {
  const sev = SEV[severity];
  const title = timing.status === "gap" ? TIMING_TITLE : "Timing check";
  return (
    <div className={`card ${CARD[severity]}`}>
      <div className="row1">
        <Badge variant="sev" tone={sev.tone}>
          {sev.label}
        </Badge>
        <span className="ttl">{title}</span>
      </div>
      <p>{timing.summary}</p>
      <div className="hdr-lbl">LLM confidence · {timing.confidence}</div>
      {timing.evidence.map((e, i) => (
        <code key={i}>{e}</code>
      ))}
    </div>
  );
}

type Item = { kind: "finding"; f: Finding; severity: Finding["severity"] } | { kind: "timing"; severity: Finding["severity"] };

function FindingsColumn({
  title,
  findings,
  timing,
}: {
  title: string;
  findings: Finding[];
  timing?: TimingCheck;
}) {
  const [expanded, setExpanded] = useState(false);
  const timingSeverity = timingCard(timing);
  const items: Item[] = [
    ...(timingSeverity ? [{ kind: "timing", severity: timingSeverity } as Item] : []),
    ...findings.map((f) => ({ kind: "finding", f, severity: f.severity }) as Item),
  ];
  // Stable sort: the timing card leads its severity group.
  const sorted = [...items].sort((a, b) => RANK[a.severity] - RANK[b.severity]);
  const hidden = sorted.length - COLLAPSE_AFTER;
  const visible = expanded ? sorted : sorted.slice(0, COLLAPSE_AFTER);

  return (
    <div className="find-col">
      <h4>
        {title} <span className="count">{countLabel(sorted.map((i) => ({ severity: i.severity }) as Finding))}</span>
      </h4>
      {visible.map((item, i) =>
        item.kind === "timing" && timing ? (
          <TimingCard key="timing" timing={timing} severity={item.severity} />
        ) : item.kind === "finding" ? (
          <FindingCard key={i} f={item.f} />
        ) : null,
      )}
      {hidden > 0 && !expanded && (
        <button type="button" className="show-all" onClick={() => setExpanded(true)}>
          show all ({sorted.length})
        </button>
      )}
    </div>
  );
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
  return (
    <div className="find-grid">
      <FindingsColumn title="Security" findings={security} />
      <FindingsColumn title="Performance" findings={performance} timing={timing} />
    </div>
  );
}
