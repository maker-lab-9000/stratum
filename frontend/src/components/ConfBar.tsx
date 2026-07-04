// Confidence bar (the Cached tile renders cache_verdict.confidence, §8.3).
// Default is the row form (bar + label); pass row={false} for a bare bar.
interface ConfBarProps {
  percent: number; // 0–100
  label?: string;
  row?: boolean;
}

export function ConfBar({ percent, label, row = true }: ConfBarProps) {
  const width = `${Math.max(0, Math.min(100, percent))}%`;
  const bar = (
    <div className="conf-bar">
      <i style={{ width }} />
    </div>
  );
  if (!row) return bar;
  return (
    <div className="conf-row">
      {bar}
      {label != null && <span className="conf-lbl">{label}</span>}
    </div>
  );
}
