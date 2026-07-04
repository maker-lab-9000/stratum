import { Fragment, useState } from "react";

// Raw response headers per request — the ground truth behind the verdict.
// Request tabs up to 8, a <select> beyond that (§8.4). Header names/values are
// rendered as React text nodes, so any injection probe in a captured value
// (e.g. `<img src=x onerror=…>`) shows as inert text — never as markup.
interface Sample {
  request: number;
  http_version?: string;
  status?: number;
  headers: [string, string][];
}

const TAB_LIMIT = 8;

function RawBody({ sample }: { sample: Sample }) {
  const statusLine = [sample.http_version, sample.status].filter((x) => x != null).join(" ");
  return (
    <pre className="raw" data-testid="raw-body">
      {statusLine && `${statusLine}\n`}
      {sample.headers.map(([k, v], i) => (
        <Fragment key={i}>
          <span className="hk">{k}</span>: <span className="hv">{v}</span>
          {"\n"}
        </Fragment>
      ))}
    </pre>
  );
}

const tabLabel = (s: Sample) => (s.request === 1 ? "Request 1 · cold" : `Request ${s.request}`);

export function RawDrawer({ samples }: { samples: Sample[] }) {
  const [active, setActive] = useState(samples[0]?.request ?? 1);
  if (samples.length === 0) return null;
  const current = samples.find((s) => s.request === active) ?? samples[0];

  return (
    <details className="drawer">
      <summary>
        <span className="chev">▶</span> Raw response headers{" "}
        <span className="hint">ground truth · per request</span>
      </summary>
      <div className="drawer-body">
        {samples.length <= TAB_LIMIT ? (
          <div className="rawtabs">
            {samples.map((s) => (
              <button
                key={s.request}
                type="button"
                className={`rawtab${s.request === active ? " on" : ""}`}
                onClick={() => setActive(s.request)}
              >
                {tabLabel(s)}
              </button>
            ))}
          </div>
        ) : (
          <div className="rawtabs">
            <select
              className="rawtab on"
              value={active}
              onChange={(e) => setActive(Number(e.target.value))}
              aria-label="Select request"
            >
              {samples.map((s) => (
                <option key={s.request} value={s.request}>
                  {tabLabel(s)}
                </option>
              ))}
            </select>
          </div>
        )}
        <RawBody sample={current} />
      </div>
    </details>
  );
}
