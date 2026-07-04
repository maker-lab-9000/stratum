import type { ReactNode } from "react";

// Shown when the LLM verdict is unavailable after a retry (§8.3): all measured
// evidence still renders below; this banner offers a re-run. A report never
// renders empty.
interface DegradedBannerProps {
  children?: ReactNode; // override the default message
  onRerun?: () => void;
}

const DEFAULT_MESSAGE = (
  <span>
    <b>Verdict unavailable.</b> The LLM analysis failed after a retry. All
    measured evidence (DNS, headers, traceroute) is shown below — re-run to retry
    the verdict.
  </span>
);

export function DegradedBanner({ children, onRerun }: DegradedBannerProps) {
  return (
    <div className="degraded" role="alert">
      {children ?? DEFAULT_MESSAGE}
      {onRerun && (
        <button type="button" className="pill" onClick={onRerun} style={{ marginLeft: "auto" }}>
          Re-run
        </button>
      )}
    </div>
  );
}
