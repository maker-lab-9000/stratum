import type { ReactNode } from "react";

import { Badge, Table, TableRow } from "../../components";
import type { BadgeTone } from "../../components";
import { edgeRttMs, formatServerMs, serverMs, splitSamples } from "./timing";
import type { CacheVerdict, RawSample, SampleState } from "./types";

// Header progression across the N samples. The per-request cache state comes
// from the LLM (sample_states); the Age / Cache-Control / Via rows and the
// TTFB / Server time rows are pulled verbatim from the captured samples (§4.3 —
// the numbers are rendered from the samples, never from LLM output). At N ≤ 6
// requests render one column each (+ a trailing cache-bust column when the probe
// ran); beyond that the state row compacts to a .strip (§8.4) and the probe is a
// one-line note under the table.
//
// 1.3.1: a fixed row whose header is absent on every column folds into one
// "Not sent: …" line; any other header whose VALUE differs across the columns
// (cache-bust probe included) gets its own row — a cache status flipping MISS → HIT,
// a rotating server id. Only values are compared, never names, so no vendor
// logic; Date is skipped (the column heads already carry the clock). Rows sort
// by fewest distinct values (flips before per-request ids), capped at six.
// 1.3.2: a row whose every column holds a different random-looking id (hex
// once separators are dropped, as in a UUID) folds into "Unique per request: …";
// a cache-bust value equal to every request's spans the probe column too.
const COLUMN_LIMIT = 6;
const CHANGED_ROW_LIMIT = 6;
const FIXED_HEADERS = ["age", "cache-control", "via"];
const SKIP_CHANGED = new Set([...FIXED_HEADERS, "date"]);

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

// A value shaped like a random id: hex once separators are dropped (UUIDs,
// trace ids). Value shape only — never the header name.
function isOpaqueId(value: string): boolean {
  const core = value.replace(/[-_.:]/g, "");
  return /^[0-9a-f]{16,}$/i.test(core) && /\d/.test(core);
}

/** Headers whose value (absent = "—") differs across the given columns, fewest
 *  distinct values first; ties keep first-appearance order. Names keep the
 *  casing they were first captured with. Rows of all-different random ids are
 *  returned separately as `ids`. */
function changingHeaders(columns: RawSample[]): { rows: { name: string; distinct: number }[]; ids: string[] } {
  const seen = new Map<string, string>();
  for (const s of columns) for (const [k] of s.headers) if (!seen.has(k.toLowerCase())) seen.set(k.toLowerCase(), k);
  const rows: { name: string; distinct: number }[] = [];
  const ids: string[] = [];
  for (const [lower, name] of seen) {
    if (SKIP_CHANGED.has(lower)) continue;
    const values = columns.map((s) => headerValue(s, lower));
    const distinct = new Set(values.map((v) => v ?? "—")).size;
    if (distinct <= 1) continue;
    if (distinct === columns.length && values.every((v) => v !== null && isOpaqueId(v))) ids.push(name);
    else rows.push({ name, distinct });
  }
  return { rows: rows.sort((a, b) => a.distinct - b.distinct), ids };
}

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
  const columns = [...requests, ...(probeColumn && probe ? [probe] : [])];
  const fixed: { label: string; header: string; muted?: boolean }[] = [
    { label: "Age", header: "Age", muted: true },
    { label: "Cache-Control", header: "Cache-Control" },
    { label: "Via", header: "Via" },
  ];
  const sent = (header: string) => [...requests, ...(probe ? [probe] : [])].some((s) => headerValue(s, header) !== null);
  const notSent = fixed.filter((f) => !sent(f.header)).map((f) => f.label);
  const { rows: changed, ids: uniqueIds } = changingHeaders(columns);
  const signals = [
    ...fixed.filter((f) => sent(f.header)),
    ...changed.slice(0, CHANGED_ROW_LIMIT).map(({ name }) => ({ label: name, header: name, muted: false })),
  ];
  const moreChanged = changed.slice(CHANGED_ROW_LIMIT).map((c) => c.name);

  // Timing rows (1.2.0) — only when the samples carry timing at all.
  const edgeRtt = edgeRttMs(requests);
  const hasTiming = [...requests, ...(probe ? [probe] : [])].some(
    (s) => typeof s.timing?.ttfb_ms === "number",
  );
  // Server time below 1 ms reads "<1 ms" (jitter can push it negative); the
  // exact value stays on hover and in the bundle facts.
  const timingRows: {
    label: string;
    value: (s: RawSample) => number | null | undefined;
    format: (v: number | null | undefined) => string;
  }[] = hasTiming
    ? [
        { label: "TTFB", value: (s) => s.timing?.ttfb_ms, format: ms },
        { label: "Server time", value: (s) => serverMs(s, edgeRtt), format: formatServerMs },
      ]
    : [];
  const exactTitle = (v: number | null | undefined, shown: string) =>
    typeof v === "number" && shown !== ms(v) ? `${v} ms measured` : undefined;

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
          // 1.3.2: the probe repeats the requests' value → one cell across it too.
          const probeSame = probeColumn && probe !== null && uniform && (headerValue(probe, header) ?? "—") === shown[0];
          return (
            <TableRow key={label}>
              <th scope="row">{label}</th>
              {compact || uniform ? (
                <td colSpan={dataSpan + (probeSame ? 1 : 0)} className={cls}>
                  {uniform ? shown[0] : shown.join("  →  ")}
                </td>
              ) : (
                shown.map((v, i) => (
                  <td key={i} className={cls}>
                    {v}
                  </td>
                ))
              )}
              {probe && !probeSame && probeCell(headerValue(probe, header) ?? "—", cls)}
            </TableRow>
          );
        })}

        {timingRows.map(({ label, value, format }) => {
          const cell = (s: RawSample) => {
            const v = value(s);
            const shown = format(v);
            return (
              <td key={s.request} className="flat" title={exactTitle(v, shown)}>
                {shown}
              </td>
            );
          };
          return (
            <TableRow key={label}>
              <th scope="row">{label}</th>
              {compact ? (
                <td className="flat">{requests.map((s) => format(value(s))).join("  →  ")}</td>
              ) : (
                requests.map(cell)
              )}
              {probeColumn && probe && cell(probe)}
            </TableRow>
          );
        })}
      </Table>
      {compact && probe && (
        <p className="prog-note">
          {`cache-bust probe · TTFB ${ms(probe.timing?.ttfb_ms)} · server time ${formatServerMs(serverMs(probe, edgeRtt))}`}
        </p>
      )}
      {notSent.length > 0 && <p className="prog-note">{`Not sent: ${notSent.join(", ")}.`}</p>}
      {uniqueIds.length > 0 && <p className="prog-note">{`Unique per request: ${uniqueIds.join(", ")}.`}</p>}
      {moreChanged.length > 0 && (
        <p className="prog-note">{`Also changed between requests: ${moreChanged.join(", ")}.`}</p>
      )}
    </>
  );
}
