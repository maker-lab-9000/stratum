import { useState } from "react";

import { Table, TableRow } from "../../components";
import type { CacheVerdict, Hop } from "./types";

// Hop ladder (§8.1.3, §8.4): timeout rows, consecutive same-ASN runs collapsed
// into an expandable summary, RTT bars normalized to this route's max RTT.
const MAX_BAR_PX = 100;
const COLLAPSE_MIN_RUN = 4; // runs of >= this many same-ASN hops collapse

interface HopLadderProps {
  hops: Hop[];
  verdict: CacheVerdict | null;
}

interface Run {
  asn: number | string | null;
  org: string | null;
  hops: Hop[];
}

function groupRuns(hops: Hop[]): Run[] {
  const runs: Run[] = [];
  for (const hop of hops) {
    const key = hop.asn;
    const last = runs[runs.length - 1];
    if (last && last.asn === key && key != null) {
      last.hops.push(hop);
    } else {
      runs.push({ asn: key, org: hop.org, hops: [hop] });
    }
  }
  return runs;
}

export function HopLadder({ hops, verdict }: HopLadderProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  if (hops.length === 0) return null;

  const maxRtt = Math.max(1, ...hops.map((h) => h.rtt_ms ?? 0));
  const edge = [...hops].reverse().find((h) => !h.unresponsive && !h.private && h.ip);
  const provider = verdict?.provider && verdict.provider !== "UNKNOWN" ? verdict.provider : "Edge";
  const runs = groupRuns(hops);

  function barWidth(rtt: number | null): number {
    if (rtt == null) return 4;
    return Math.max(4, Math.round((rtt / maxRtt) * MAX_BAR_PX));
  }

  function renderHop(hop: Hop) {
    if (hop.unresponsive) {
      return (
        <TableRow key={hop.n} state="timeout">
          <td className="n">{hop.n}</td>
          <td>* * *</td>
          <td>—</td>
          <td>—</td>
          <td>—</td>
          <td>—</td>
        </TableRow>
      );
    }
    const isEdge = edge != null && hop.n === edge.n;
    const asnCell = hop.asn != null ? (
      <>
        <b>AS{hop.asn}</b> {hop.org}
        {isPeering(hop.org) && <span className="peer-tag">peering</span>}
      </>
    ) : hop.private ? (
      "private LAN"
    ) : (
      hop.org ?? "—"
    );
    return (
      <TableRow key={hop.n} state={isEdge ? "served" : hop.private ? "private" : undefined}>
        <td className="n">{hop.n}</td>
        <td>{hop.ip}</td>
        <td className="host">
          {hop.rdns ?? "—"}
          {isEdge && <span className="edge-anchor">= {provider} Edge ↓</span>}
        </td>
        <td className="asn">{asnCell}</td>
        <td>{hop.city ? <span className="city">{hop.city}</span> : "—"}</td>
        <td>
          <div className="lat">
            <span className="bar" style={{ width: `${barWidth(hop.rtt_ms)}px` }} />
            <span className="ms">{hop.rtt_ms != null ? `${hop.rtt_ms} ms` : "—"}</span>
          </div>
        </td>
      </TableRow>
    );
  }

  return (
    <div style={{ marginTop: 14 }}>
      <Table variant="hops" head={["#", "IP address", "Reverse DNS", "ASN / provider", "City", "RTT"]}>
        {runs.flatMap((run, ri) => {
          const collapsible = run.hops.length >= COLLAPSE_MIN_RUN && run.asn != null;
          if (collapsible && !expanded.has(ri)) {
            return [
              <TableRow key={`g${ri}`} state="asnGroup">
                <td className="n">{run.hops[0].n}–{run.hops[run.hops.length - 1].n}</td>
                <td colSpan={5} onClick={() => setExpanded((s) => new Set(s).add(ri))}>
                  <b>AS{run.asn}</b> {run.org}
                  <span className="cnt">▸ {run.hops.length} hops · click to expand</span>
                </td>
              </TableRow>,
            ];
          }
          return run.hops.map(renderHop);
        })}
      </Table>
    </div>
  );
}

function isPeering(org: string | null): boolean {
  if (!org) return false;
  return /\b(ix|cix|internet exchange)\b/i.test(org);
}
