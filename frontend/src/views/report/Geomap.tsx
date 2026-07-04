import { Fragment } from "react";

import { cityLatLon } from "./cities";
import { graticule, projectNodes, type GeoNode } from "./projection";
import type { Hop } from "./types";

// Route geography (§8.1.3, §8.2): a tile-free coordinate map computed from
// enriched hop cities. When fewer than two points are plottable, falls back to
// the route-strip renderer behind the same interface. Vantage is disclosed.
interface GeomapProps {
  vantage: string | null;
  hops: Hop[];
}

function haversineKm(a: [number, number], b: [number, number]): number {
  const R = 6371;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)));
}

export function Geomap({ vantage, hops }: GeomapProps) {
  const responsive = hops.filter((h) => !h.unresponsive && !h.private && h.ip);
  const edge = responsive[responsive.length - 1];
  const vantageCity = vantage?.split(/[,·]/)[0]?.trim() ?? null;

  const vantageCoords = cityLatLon(vantageCity);
  const edgeCoords = cityLatLon(edge?.city);

  const canMap = vantageCoords && edgeCoords && !(vantageCoords[0] === edgeCoords[0] && vantageCoords[1] === edgeCoords[1]);

  if (canMap) {
    const nodes: GeoNode[] = [
      { lat: vantageCoords![0], lon: vantageCoords![1], label: vantageCity ?? "Vantage", sub: "access", tag: "vantage", kind: "vantage" },
      { lat: edgeCoords![0], lon: edgeCoords![1], label: edge!.city ?? "Edge", sub: `${edge!.org ?? "edge"}`, tag: "serving PoP", kind: "pop" },
    ];
    const placed = projectNodes(nodes);
    const grid = graticule(placed);
    const path = `M${placed[0].x},${placed[0].y} C${placed[0].x},${(placed[0].y + placed[1].y) / 2} ${placed[1].x},${(placed[0].y + placed[1].y) / 2} ${placed[1].x},${placed[1].y}`;
    const distance = haversineKm(vantageCoords!, edgeCoords!);

    return (
      <div className="panel geo-wrap">
        <div className="geo-head">
          <h3>Route geography</h3>
          <div className="vantage">
            Vantage <b>{vantage}</b>
          </div>
        </div>
        <div className="geomap" data-testid="geomap">
          <div className="dots" />
          {grid.vertical.map((g, i) => (
            <div key={`v${i}`} className="grat v" style={{ left: `${g.x}%` }}>
              <span className="glab">{g.label}</span>
            </div>
          ))}
          {grid.horizontal.map((g, i) => (
            <div key={`h${i}`} className="grat h" style={{ top: `${g.y}%` }}>
              <span className="glab">{g.label}</span>
            </div>
          ))}
          <svg className="geosvg" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path className="route-path" d={path} />
          </svg>
          {placed.map((n, i) => (
            <div
              key={i}
              className={`gnode ${n.kind}`}
              data-testid={`gnode-${n.kind}`}
              style={{ left: `${n.x}%`, top: `${n.y}%` }}
            >
              <div className="pt" />
              <div className="glabel" style={{ top: `${n.labelY - n.y}%` }}>
                <span className="gtag">{n.tag}</span>
                <br />
                {n.label}
                {n.sub && <span className="sub">{n.sub}</span>}
              </div>
            </div>
          ))}
        </div>
        <div className="geo-foot">
          <span>
            <b>Distance</b> ~{distance} km
          </span>
          {edge?.rtt_ms != null && (
            <span>
              <b>RTT to edge</b> {edge.rtt_ms} ms
            </span>
          )}
          <span>
            <b>Geo source</b> rDNS + MaxMind ASN
          </span>
        </div>
      </div>
    );
  }

  return <RouteStrip vantage={vantage} hops={hops} />;
}

// Fallback: vantage → transit cities → PoP on a line with RTT annotations.
function RouteStrip({ vantage, hops }: GeomapProps) {
  const stops: { name: string; sub: string; vantage?: boolean }[] = [];
  const vantageCity = vantage?.split(/[,·]/)[0]?.trim() ?? "Vantage";
  stops.push({ name: vantageCity, sub: "vantage", vantage: true });

  let lastCity: string | null = null;
  for (const hop of hops) {
    if (hop.unresponsive || hop.private) continue;
    const city = hop.city ?? hop.org ?? hop.ip ?? "?";
    if (city !== lastCity) {
      stops.push({ name: city, sub: hop.rtt_ms != null ? `${hop.rtt_ms} ms` : "" });
      lastCity = city;
    }
  }

  return (
    <div className="panel geo-wrap">
      <div className="geo-head">
        <h3>Route geography</h3>
        <div className="vantage">
          Vantage <b>{vantage}</b>
        </div>
      </div>
      <div className="route-strip" data-testid="route-strip">
        {stops.map((s, i) => (
          <Fragment key={i}>
            {i > 0 && <div className="seg-line" />}
            <div className={s.vantage ? "stop vantage" : "stop"}>
              <div className="pt" />
              <div className="nm">{s.name}</div>
              <div className="sub">{s.sub}</div>
            </div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
