import { Fragment } from "react";

import type { Investigation, InvestigationLogEntry, RawSample } from "./types";

// What the model tried (1.4.0): one row per tool call from the pipeline's call
// log, in order — including refused and failed calls — with the model's own
// `observed` text for the request when it wrote one. The log is the
// deterministic record; the model's steps are its narration; they are shown
// together, never merged. Each row expands to the full record.
const offset = (entry: InvestigationLogEntry, first: number) =>
  `+${Math.round((entry.asked_at_ms - first) / 1000)} s`;

function status(entry: InvestigationLogEntry): string {
  if (entry.refused) return `refused: ${entry.refused}`;
  const r = entry.response;
  if (!r) return "no response";
  if ("error" in r) return `no response: ${r.error ?? "unknown error"}`;
  return r.status != null ? String(r.status) : "no response";
}

function RawHeaders({ headers }: { headers: [string, string][] }) {
  return (
    <pre className="raw">
      {headers.map(([k, v], i) => (
        <Fragment key={i}>
          <span className="hk">{k}</span>: <span className="hv">{v}</span>
          {"\n"}
        </Fragment>
      ))}
    </pre>
  );
}

export function Tried({
  log,
  investigation,
  samples,
}: {
  log: InvestigationLogEntry[];
  investigation: Investigation | null;
  samples: RawSample[];
}) {
  if (log.length === 0) return null;
  const first = log[0].asked_at_ms;
  const observed = new Map((investigation?.steps ?? []).map((s) => [s.request, s.observed]));
  const sampleFor = (n: number | null) => (n == null ? undefined : samples.find((s) => s.request === n));

  return (
    <section className="tried">
      <h2>What the model tried</h2>
      {investigation?.summary && <p className="lede">{investigation.summary}</p>}
      <ol className="tried-list">
        {log.map((entry) => {
          const headers = Object.entries(entry.input.headers ?? {});
          const sample = sampleFor(entry.request);
          const note = entry.request != null ? observed.get(entry.request) : undefined;
          return (
            <li key={entry.n} className={`tried-row${entry.refused ? " refused" : ""}`}>
              <div className="tried-n">
                <b>{entry.n}</b>
                <span>{offset(entry, first)}</span>
              </div>
              <div className="tried-body">
                <div className="tried-asked">
                  {headers.length === 0 && <code>no extra headers</code>}
                  {headers.map(([k, v]) => (
                    <code key={k}>
                      {k}: {v}
                    </code>
                  ))}
                  {entry.input.cache_bust && <code>+ cache-bust query</code>}
                </div>
                {entry.input.reason && <p className="tried-reason">{entry.input.reason}</p>}
                {note && <p className="tried-observed">{note}</p>}
                <details className="tried-more">
                  <summary>The full call</summary>
                  {entry.model_said && (
                    <p className="tried-said">
                      The model said: <q>{entry.model_said}</q>
                    </p>
                  )}
                  {entry.sent && (
                    <>
                      <p className="note">
                        Sent: {entry.sent.method} {entry.sent.url}
                      </p>
                      <RawHeaders headers={entry.sent.headers} />
                    </>
                  )}
                  {sample && sample.headers.length > 0 && (
                    <>
                      <p className="note">
                        Response: {[sample.http_version, sample.status].filter((x) => x != null).join(" ")}
                      </p>
                      <RawHeaders headers={sample.headers} />
                    </>
                  )}
                  <p className="note">Returned to the model:</p>
                  <pre className="raw">{JSON.stringify(entry.returned, null, 1)}</pre>
                </details>
              </div>
              <div className="tried-status">{status(entry)}</div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
