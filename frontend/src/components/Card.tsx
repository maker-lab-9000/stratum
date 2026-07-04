import type { ReactNode } from "react";

import { Badge } from "./Badge";

// Finding card (security / performance). Colored left border by severity;
// evidence header rendered in monospace. `unverified` shows the amber-dashed tag
// when the citation failed machine-checking (§8.3).
export type Severity = "crit" | "warn" | "info";

interface CardProps {
  severity: Severity;
  title: ReactNode;
  children?: ReactNode; // description prose
  evidenceHeader?: string;
  unverified?: boolean;
}

export function Card({ severity, title, children, evidenceHeader, unverified }: CardProps) {
  return (
    <div className={`card ${severity}`}>
      <div className="row1">
        <Badge variant="sev" tone={severity}>
          {severity}
        </Badge>
        <span className="ttl">{title}</span>
        {unverified && <Badge variant="unverified" />}
      </div>
      {children}
      {evidenceHeader && (
        <>
          <div className="hdr-lbl">Evidence header</div>
          <code>{evidenceHeader}</code>
        </>
      )}
    </div>
  );
}
