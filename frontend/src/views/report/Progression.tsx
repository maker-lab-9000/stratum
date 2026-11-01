import type { ReactNode } from "react";

import { Badge, Table, TableRow } from "../../components";
import type { BadgeTone } from "../../components";
import { edgeRttMs, serverMs, splitSamples } from "./timing";
import type { CacheVerdict, RawSample, SampleState } from "./types";

// Header progression across the N samples. The per-request cache state comes
// from the LLM (sample_states); the Age / Cache-Control / Via rows and the
// TTFB / Server time rows are pulled verbatim from the captured samples (§4.3 —
// the numbers are rendered from the samples, never from LLM output). At N ≤ 6
// requests render one column each (+ a trailing cache-bust column when the probe
// ran); beyond that the state row compacts to a .strip (§8.4) and the probe is a
// one-line note under the table.
const COLUMN_LIMIT = 6;

// Case-insensitive header lookup; repeated headers join with ", " (verbatim).
function headerValue(sample: RawSample, name: string): string | null {
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

const ms = (v: number | null | undefined) => (typeof v === "number" ? `${v} ms` : "—");

// "Request k" column header with a timing sub-label derived from started_at_ms
// (first request = cold; later requests = +Ns after it). Purely a clock fact.
function columnHead(sample: RawSample, firstStart: number | null): ReactNode {
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

const probeHead: ReactNode = (
  <>
    <span className="rq">cache-bust</span>probe
  </>
);

export function Progression({ verdict, samples }: { verdict: CacheVerdict | null; samples: RawSample[] }) {
  const { requests, probe } = splitSamples(samples);
  const n = requests.length;
  if (n === 0) return null;
  const compact = n > COLUMN_LIMIT;
  const probeColumn = !compact && probe !== null;
  const firstStart = requests[0]?.started_at_ms ?? null;
  const states: SampleState[] = verdict?.sample_states ?? [];
  const stateFor = (request: number) => states.find((s) => s.request === request)?.state ?? "UNKNOWN";

  // Verbatim signal rows: label + per-request value. Uniform values collapse to
  // one colspan cell (the mockup's Cache-Control / Via treatment).
  const signals: { label: string; header: string; muted?: boolean }[] = [
    { label: "Age", header: "Age", muted: true },
    { label: "Cache-Control", header: "Cache-Control" },
    { label: "Via", header: "Via" },
  ];

  // Timing rows (1.2.0) — only when the samples carry timing at all.
  const edgeRtt = edgeRttMs(requests);
  const hasTiming = [...requests, ...(probe ? [probe] : [])].some(
    (s) => typeof s.timing?.ttfb_ms === "number",
  );
  const timingRows: { label: string; value: (s: RawSample) => number | null | undefined }[] = hasTiming
    ? [
        { label: "TTFB", value: (s) => s.timing?.ttfb_ms },
        { label: "Server time", value: (s) => serverMs(s, edgeRtt) },
      ]
    : [];

  const head: ReactNode[] = compact
    ? ["Signal", "Across requests"]
    : [
        "Signal",
        ...requests.map((s) => columnHead(s, firstStart)),
        ...(probeColumn ? [probeHead] : []),
      ];
  const dataSpan = compact ? 1 : n;
  const probeCell = (content: ReactNode, className?: string) =>
    probeColumn ? <td className={className}>{content}</td> : null;

  return (
    <>
      <Table variant="prog" head={head}>
        {/* The model's per-request reading — the only interpreted row (1.3.0: labelled as such). */}
        {verdict && (
        <TableRow>
          <th scope="row">Model's reading</th>
          {compact ? (
            <td>
              <span className="strip">
                {requests.map((s) => {
                  const st = stateFor(s.request);
                  return <i key={s.request} className={stripClass(st)} title={`Request ${s.request}: ${st}`} />;
                })}
              </span>
            </td>
          ) : (
            requests.map((s) => {
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
          {probeCell(null)}
        </TableRow>
        )}

        {signals.map(({ label, header, muted }) => {
          const values = requests.map((s) => headerValue(s, header));
          const shown = values.map((v) => v ?? "—");
          const uniform = shown.every((v) => v === shown[0]);
          const cls = muted ? "flat" : undefined;
          return (
            <TableRow key={label}>
              <th scope="row">{label}</th>
              {compact || uniform ? (
                <td colSpan={dataSpan} className={cls}>
                  {uniform ? shown[0] : shown.join("  →  ")}
                </td>
              ) : (
                shown.map((v, i) => (
                  <td key={i} className={cls}>
                    {v}
                  </td>
                ))
              )}
              {probe && probeCell(headerValue(probe, header) ?? "—", cls)}
            </TableRow>
          );
        })}

        {timingRows.map(({ label, value }) => (
          <TableRow key={label}>
            <th scope="row">{label}</th>
            {compact ? (
              <td className="flat">{requests.map((s) => ms(value(s))).join("  →  ")}</td>
            ) : (
              requests.map((s) => (
                <td key={s.request} className="flat">
                  {ms(value(s))}
                </td>
              ))
            )}
            {probe && probeCell(ms(value(probe)), "flat")}
          </TableRow>
        ))}
      </Table>
      {compact && probe && (
        <p className="prog-note">
          {`cache-bust probe · TTFB ${ms(probe.timing?.ttfb_ms)} · server time ${ms(serverMs(probe, edgeRtt))}`}
        </p>
      )}
    </>
  );
}
