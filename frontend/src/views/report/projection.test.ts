import { expect, test } from "vitest";

import { projectNodes, type GeoNode } from "./projection";

// T18 scenario 4: projection + auto-fit + label collision handling.

test("Berlin -> Ashburn: both nodes inside the padded viewport", () => {
  const pad = 12;
  const nodes: GeoNode[] = [
    { lat: 52.52, lon: 13.405, label: "Berlin", kind: "vantage" },
    { lat: 39.04, lon: -77.49, label: "Ashburn", kind: "pop" },
  ];
  const placed = projectNodes(nodes, pad);
  expect(placed).toHaveLength(2);
  for (const n of placed) {
    expect(n.x).toBeGreaterThanOrEqual(pad);
    expect(n.x).toBeLessThanOrEqual(100 - pad);
    expect(n.y).toBeGreaterThanOrEqual(pad);
    expect(n.y).toBeLessThanOrEqual(100 - pad);
  }
  // The two nodes are at opposite corners of the fitted box.
  expect(Math.abs(placed[0].x - placed[1].x)).toBeGreaterThan(50);
});

test("3 near-colinear nodes -> labels do not overlap", () => {
  const nodes: GeoNode[] = [
    { lat: 50.0, lon: 8, label: "a", kind: "hop" },
    { lat: 50.0, lon: 9, label: "b", kind: "hop" },
    { lat: 50.0, lon: 10, label: "c", kind: "hop" }, // same lat -> labels would stack
  ];
  const placed = projectNodes(nodes, 12);
  const labelYs = placed.map((n) => n.labelY).sort((a, b) => a - b);
  for (let i = 1; i < labelYs.length; i++) {
    expect(labelYs[i] - labelYs[i - 1]).toBeGreaterThanOrEqual(12 - 0.001);
  }
});
