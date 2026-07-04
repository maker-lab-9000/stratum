import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  createAnalysis,
  getModels,
  type CreateAnalysisBody,
  type ProviderInfo,
} from "../api/client";

interface HeaderRow {
  name: string;
  value: string;
}

function isValidHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function Launch() {
  const navigate = useNavigate();
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");

  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // advanced
  const [requestCount, setRequestCount] = useState("4");
  const [intervalMs, setIntervalMs] = useState("0");
  const [warm, setWarm] = useState(true);
  const [geoHint, setGeoHint] = useState("");
  const [headers, setHeaders] = useState<HeaderRow[]>([{ name: "", value: "" }]);

  useEffect(() => {
    getModels()
      .then((data) => {
        setProviders(data.providers);
        if (data.providers.length > 0) {
          setProvider(data.providers[0].id);
          setModel(data.providers[0].models[0]?.id ?? "");
        }
      })
      .catch(() => setProviders([]));
  }, []);

  const currentProvider = providers?.find((p) => p.id === provider);
  const noProviders = providers !== null && providers.length === 0;

  function onProviderChange(id: string) {
    setProvider(id);
    const next = providers?.find((p) => p.id === id);
    setModel(next?.models[0]?.id ?? "");
  }

  function updateHeader(index: number, patch: Partial<HeaderRow>) {
    setHeaders((rows) => rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitError(null);
    if (!isValidHttpUrl(url)) {
      setUrlError("Enter an absolute http(s) URL, e.g. https://example.com/");
      return;
    }
    setUrlError(null);
    if (!provider || !model) return;

    const extra_request_headers: Record<string, string> = {};
    for (const row of headers) {
      if (row.name.trim()) extra_request_headers[row.name.trim()] = row.value;
    }

    const body: CreateAnalysisBody = {
      url,
      provider,
      model,
      options: {
        request_count: Number(requestCount) || 4,
        interval_ms: Number(intervalMs) || 0,
        warm,
        extra_request_headers,
        geo_hint: geoHint.trim() || null,
      },
    };

    setSubmitting(true);
    try {
      const { id } = await createAnalysis(body);
      // Pass the request count so the live-run stepper can render the N request
      // steps immediately, before the sample event reveals N.
      navigate(`/runs/${id}`, { state: { requestCount: body.options.request_count } });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
      setSubmitting(false);
    }
  }

  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: "72px 24px 80px" }}>
      <div className="brand" style={{ justifyContent: "center", fontSize: 22, marginBottom: 8 }}>
        <span className="dot" />
        Stratum
        <span className="sub">cache &amp; delivery analyzer</span>
      </div>
      <p style={{ textAlign: "center", color: "var(--mid)", marginTop: 0, marginBottom: 32 }}>
        Give it a URL. It collects the evidence; the model reads it.
      </p>

      <form onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label className="field-label" htmlFor="url">
            Target URL
          </label>
          <input
            id="url"
            className={urlError ? "input invalid" : "input"}
            type="text"
            inputMode="url"
            placeholder="https://www.example.com/page"
            value={url}
            aria-invalid={urlError ? true : undefined}
            aria-describedby={urlError ? "url-error" : undefined}
            onChange={(e) => {
              setUrl(e.target.value);
              if (urlError) setUrlError(null);
            }}
          />
          {urlError && (
            <span id="url-error" className="field-error" role="alert">
              {urlError}
            </span>
          )}
        </div>

        {noProviders ? (
          <div className="empty-state" style={{ marginTop: 16 }}>
            No LLM providers configured. Set <code>ANTHROPIC_API_KEY</code> or{" "}
            <code>OPENROUTER_API_KEY</code> in the environment and reload.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 16 }}>
            <div className="field">
              <label className="field-label" htmlFor="provider">
                Provider
              </label>
              <select
                id="provider"
                className="select"
                value={provider}
                onChange={(e) => onProviderChange(e.target.value)}
              >
                {(providers ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="model">
                Model
              </label>
              <select
                id="model"
                className="select"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {(currentProvider?.models ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        <details className="disclosure" style={{ marginTop: 18 }}>
          <summary>
            <span className="chev">▸</span> Advanced
          </summary>
          <div style={{ display: "grid", gap: 14, paddingTop: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div className="field">
                <label className="field-label" htmlFor="request-count">
                  Requests
                </label>
                <input
                  id="request-count"
                  className="input"
                  type="number"
                  min={1}
                  max={20}
                  value={requestCount}
                  onChange={(e) => setRequestCount(e.target.value)}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="interval">
                  Interval (ms)
                </label>
                <input
                  id="interval"
                  className="input"
                  type="number"
                  min={0}
                  max={60000}
                  value={intervalMs}
                  onChange={(e) => setIntervalMs(e.target.value)}
                />
              </div>
            </div>
            <label className="check">
              <input type="checkbox" checked={warm} onChange={(e) => setWarm(e.target.checked)} />
              Warm the cache (browser navigation) before sampling
            </label>
            <div className="field">
              <label className="field-label" htmlFor="geo-hint">
                Geo hint
              </label>
              <input
                id="geo-hint"
                className="input"
                type="text"
                placeholder="optional, e.g. fra"
                value={geoHint}
                onChange={(e) => setGeoHint(e.target.value)}
              />
            </div>
            <div className="field">
              <span className="field-label">Custom request headers</span>
              {headers.map((row, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8 }}>
                  <input
                    className="input"
                    aria-label={`header ${i + 1} name`}
                    placeholder="Header-Name"
                    value={row.name}
                    onChange={(e) => updateHeader(i, { name: e.target.value })}
                  />
                  <input
                    className="input"
                    aria-label={`header ${i + 1} value`}
                    placeholder="value"
                    value={row.value}
                    onChange={(e) => updateHeader(i, { value: e.target.value })}
                  />
                  <button
                    type="button"
                    className="pill"
                    aria-label={`add header row`}
                    onClick={() => setHeaders((r) => [...r, { name: "", value: "" }])}
                  >
                    +
                  </button>
                </div>
              ))}
            </div>
          </div>
        </details>

        <button
          type="submit"
          className="btn"
          disabled={noProviders || submitting}
          style={{ width: "100%", marginTop: 22, padding: "12px 16px" }}
        >
          {submitting ? "Starting…" : "Run analysis"}
        </button>
        {submitError && (
          <span className="field-error" role="alert" style={{ display: "block", marginTop: 8 }}>
            {submitError}
          </span>
        )}
      </form>
    </main>
  );
}
