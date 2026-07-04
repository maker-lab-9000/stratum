import { useState } from "react";

import { Badge } from "../../components";
import type { BadgeTone } from "../../components";
import type { Finding } from "./types";

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

function FindingsColumn({ title, findings }: { title: string; findings: Finding[] }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...findings].sort((a, b) => RANK[a.severity] - RANK[b.severity]);
  const hidden = sorted.length - COLLAPSE_AFTER;
  const visible = expanded ? sorted : sorted.slice(0, COLLAPSE_AFTER);

  return (
    <div className="find-col">
      <h4>
        {title} <span className="count">{countLabel(findings)}</span>
      </h4>
      {visible.map((f, i) => (
        <FindingCard key={i} f={f} />
      ))}
      {hidden > 0 && !expanded && (
        <button type="button" className="show-all" onClick={() => setExpanded(true)}>
          show all ({sorted.length})
        </button>
      )}
    </div>
  );
}

export function Findings({ security, performance }: { security: Finding[]; performance: Finding[] }) {
  return (
    <div className="find-grid">
      <FindingsColumn title="Security" findings={security} />
      <FindingsColumn title="Performance" findings={performance} />
    </div>
  );
}
