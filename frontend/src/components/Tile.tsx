import type { ReactNode } from "react";

// Verdict tile (§8.1.3). One shared value size — long vendor names wrap; no
// per-tile overrides. status="hit" only for served-from-cache; "unknown" is the
// dashed-grey degraded/ambiguous treatment.
export type TileStatus = "hit" | "warn" | "accent" | "unknown";

interface TileProps {
  label: ReactNode;
  value: ReactNode;
  foot?: ReactNode;
  status?: TileStatus;
  children?: ReactNode; // e.g. a <ConfBar/> on the Cached tile
}

export function Tile({ label, value, foot, status, children }: TileProps) {
  return (
    <div className={status ? `tile is-${status}` : "tile"}>
      <span className="edge" />
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {foot != null && <div className="foot">{foot}</div>}
      {children}
    </div>
  );
}
