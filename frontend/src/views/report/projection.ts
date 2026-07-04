// Equirectangular projection + viewport auto-fit + label collision handling for
// the route geomap (§8.2). The mockup's node positions are hardcoded; the real
// component computes them from lat/lon. preserveAspectRatio is "none" (the SVG
// stretches), matching the mockup, so x and y scale independently.

export type NodeKind = "vantage" | "pop" | "hop";

export interface GeoNode {
  lat: number;
  lon: number;
  label: string;
  sub?: string;
  tag?: string;
  kind: NodeKind;
}

export interface PlacedNode extends GeoNode {
  x: number; // % within [padding, 100-padding]
  y: number;
  labelY: number; // % — collision-shifted so labels don't overlap
}

const DEFAULT_PADDING = 12;
const MIN_LABEL_GAP = 12;

export function projectNodes(nodes: GeoNode[], padding = DEFAULT_PADDING): PlacedNode[] {
  if (nodes.length === 0) return [];
  // equirectangular: x ∝ lon, y ∝ -lat (north is up).
  const raw = nodes.map((n) => ({ node: n, rx: n.lon, ry: -n.lat }));
  const xs = raw.map((r) => r.rx);
  const ys = raw.map((r) => r.ry);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const spanX = Math.max(...xs) - minX || 1;
  const spanY = Math.max(...ys) - minY || 1;
  const inner = 100 - 2 * padding;

  const placed: PlacedNode[] = raw.map(({ node, rx, ry }) => {
    const y = padding + ((ry - minY) / spanY) * inner;
    return {
      ...node,
      x: padding + ((rx - minX) / spanX) * inner,
      y,
      labelY: y,
    };
  });

  resolveLabelCollisions(placed, padding);
  return placed;
}

// Push overlapping labels apart vertically, staying inside the padded viewport.
function resolveLabelCollisions(nodes: PlacedNode[], padding: number): void {
  const order = [...nodes].sort((a, b) => a.labelY - b.labelY);
  for (let i = 1; i < order.length; i++) {
    if (order[i].labelY - order[i - 1].labelY < MIN_LABEL_GAP) {
      order[i].labelY = Math.min(100 - padding, order[i - 1].labelY + MIN_LABEL_GAP);
    }
  }
}

// Graticule lines derived from the nodes (rounded lon/lat), so the grid aligns
// with the plotted points. Deduped by rounded degree.
export interface Graticule {
  vertical: { x: number; label: string }[];
  horizontal: { y: number; label: string }[];
}

export function graticule(placed: PlacedNode[]): Graticule {
  const vertical = new Map<number, { x: number; label: string }>();
  const horizontal = new Map<number, { y: number; label: string }>();
  for (const n of placed) {
    const lonDeg = Math.round(n.lon);
    const latDeg = Math.round(n.lat);
    vertical.set(lonDeg, { x: n.x, label: `${Math.abs(lonDeg)}°${lonDeg >= 0 ? "E" : "W"}` });
    horizontal.set(latDeg, { y: n.y, label: `${Math.abs(latDeg)}°${latDeg >= 0 ? "N" : "S"}` });
  }
  return { vertical: [...vertical.values()], horizontal: [...horizontal.values()] };
}
