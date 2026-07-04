import type { ReactNode } from "react";

import { Badge, Table, TableRow } from "../../components";
import type { BadgeTone } from "../../components";
import type { CacheVerdict, SampleState } from "./types";

// Header progression across the N samples. The per-request cache state comes
// from the LLM (sample_states); the Age / Cache-Control / Via rows are pulled
// verbatim from the captured samples (§4.3 — the numbers are rendered from the
// samples, never from LLM output). At N ≤ 6 requests render one column each;
// beyond that the state row compacts to a .strip (§8.4).
interface Sample {
  request: number;
  http_version?: string;
  status?: number;
  started_at_ms?: number;
  headers: [string, string][];
}

const COLUMN_LIMIT = 6;

// Case-insensitive header lookup; repeated headers join with ", " (verbatim).
function headerValue(sample: Sample, name: string): string | null {
  const lower = name.toLowerCase();
  const vals = sample.headers.filter(([k]) => k.toLowerCase() === lower).map(([, v]) => v);
  return vals.length ? vals.join(", ") : null;
}

function stateTag(state: string): { tone: BadgeTone; text: string } {
  if (state === "HIT") return { tone: "hit", text: "HIT" };
  if (state === "UNKNOWN") return { tone: "unknown", text: "UNKNOWN" };
  return { tone: "miss", text: state };
}

// h/m/u strip cell class for the compact (N>6) state row.
const stripClass = (state: string) => (state === "HIT" ? "h" : state === "UNKNOWN" ? "u" : "m");

// "Request k" column header with a timing sub-label derived from started_at_ms
// (first request = cold; later requests = +Ns after it). Purely a clock fact.
function columnHead(sample: Sample, firstStart: number | null): ReactNode {
  let timing = "";
  if (sample.request === 1) timing = "cold";
  else if (firstStart != null && sample.started_at_ms != null)
    timing = `+${Math.round((sample.started_at_ms - firstStart) / 1000)}s`;
  return (
    <>
      <span className="rq">Request {sample.request}</span>
      {timing}
    </>
  );
}

export function Progression({ verdict, samples }: { verdict: CacheVerdict; samples: Sample[] }) {
  const n = samples.length;
  if (n === 0) return null;
  const compact = n > COLUMN_LIMIT;
  const firstStart = samples[0]?.started_at_ms ?? null;
  const states: SampleState[] = verdict.sample_states ?? [];
  const stateFor = (request: number) => states.find((s) => s.request === request)?.state ?? "UNKNOWN";

  // Verbatim signal rows: label + per-request value. Uniform values collapse to
  // one colspan cell (the mockup's Cache-Control / Via treatment).
  const signals: { label: string; header: string; muted?: boolean }[] = [
    { label: "Age", header: "Age", muted: true },
    { label: "Cache-Control", header: "Cache-Control" },
    { label: "Via", header: "Via" },
  ];

  const head: ReactNode[] = compact
    ? ["Signal", "Across requests"]
    : ["Signal", ...samples.map((s) => columnHead(s, firstStart))];
  const dataSpan = compact ? 1 : n;

  return (
    <Table variant="prog" head={head}>
      {/* Per-request cache state — the LLM's interpretation of each sample. */}
      <TableRow state={verdict.cached ? "served" : undefined}>
        <th scope="row">Cache state</th>
        {compact ? (
          <td>
            <span className="strip">
              {samples.map((s) => {
                const st = stateFor(s.request);
                return <i key={s.request} className={stripClass(st)} title={`Request ${s.request}: ${st}`} />;
              })}
            </span>
          </td>
        ) : (
          samples.map((s) => {
            const t = stateTag(stateFor(s.request));
            return (
              <td key={s.request}>
                <Badge variant="tag" tone={t.tone}>
                  {t.text}
                </Badge>
              </td>
            );
          })
        )}
      </TableRow>

      {signals.map(({ label, header, muted }) => {
        const values = samples.map((s) => headerValue(s, header));
        const shown = values.map((v) => v ?? "—");
        const uniform = shown.every((v) => v === shown[0]);
        return (
          <TableRow key={label}>
            <th scope="row">{label}</th>
            {compact || uniform ? (
              <td colSpan={dataSpan} className={muted ? "flat" : undefined}>
                {uniform ? shown[0] : shown.join("  →  ")}
              </td>
            ) : (
              shown.map((v, i) => (
                <td key={i} className={muted ? "flat" : undefined}>
                  {v}
                </td>
              ))
            )}
          </TableRow>
        );
      })}
    </Table>
  );
}
