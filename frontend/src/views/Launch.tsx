import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createAnalysis,
  getModels,
  getProviderModels,
  listAnalyses,
  type CreateAnalysisBody,
  type ModelInfo,
  type ProviderInfo,
  type Report,
} from "../api/client";
import { ConfidenceMeter, TopBar } from "../components";
import { isInProgress, servedPhrase } from "./report/story";
import type { CacheVerdict } from "./report/types";
import { isDegraded } from "./report/types";

// Above this many models, the picker gets a filter box (OpenRouter lists ~300).
const MODEL_FILTER_THRESHOLD = 15;

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
  // Live model lists fetched per provider on demand, cached by provider id.
  const [liveModels, setLiveModels] = useState<Record<string, ModelInfo[]>>({});
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelFilter, setModelFilter] = useState("");

  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // advanced
  const [requestCount, setRequestCount] = useState("4");
  const [intervalMs, setIntervalMs] = useState("0");
  const [warm, setWarm] = useState(true);
  const [cacheBust, setCacheBust] = useState(true);
  const [investigate, setInvestigate] = useState(false);
  const [geoHint, setGeoHint] = useState("");
  const [headers, setHeaders] = useState<HeaderRow[]>([{ name: "", value: "" }]);
  const [recent, setRecent] = useState<Report[]>([]);

  useEffect(() => {
    listAnalyses({ limit: 5 })
      .then((data) => setRecent(data.reports ?? []))
      .catch(() => setRecent([]));
  }, []);

  useEffect(() => {
    getModels()
      .then((data) => {
        setProviders(data.providers);
        if (data.providers.length > 0) {
          setProvider(data.providers[0].id); // triggers the live-models effect below
          setModel(data.providers[0].models[0]?.id ?? "");
        }
      })
      .catch(() => setProviders([]));
  }, []);

  const currentProvider = providers?.find((p) => p.id === provider);
  const noProviders = providers !== null && providers.length === 0;

  // Fetch the selected provider's live model list on demand (cached per
  // provider). The static list from /api/models seeds the picker instantly; the
  // live list replaces it when it lands, falling back to static on any error.
  useEffect(() => {
    if (!provider || liveModels[provider]) return;
    const staticModels = providers?.find((p) => p.id === provider)?.models ?? [];
    let cancelled = false;
    setModelsLoading(true);
    getProviderModels(provider)
      .then(({ models }) => (models.length ? models : staticModels))
      .catch(() => staticModels)
      .then((list) => {
        if (cancelled) return;
        setLiveModels((prev) => ({ ...prev, [provider]: list }));
        // Keep the current selection if it survived; else default to the first.
        setModel((m) => (list.some((x) => x.id === m) ? m : list[0]?.id ?? ""));
      })
      .finally(() => !cancelled && setModelsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [provider, providers, liveModels]);

  function onProviderChange(id: string) {
    setProvider(id);
    setModelFilter("");
    // Show the cached/static list immediately; the effect fetches live if needed.
    const next = providers?.find((p) => p.id === id);
    const seeded = liveModels[id] ?? next?.models ?? [];
    setModel(seeded[0]?.id ?? "");
  }

  // Models shown in the picker: live list if fetched, else the static seed.
  const providerModels = liveModels[provider] ?? currentProvider?.models ?? [];
  const showModelFilter = providerModels.length > MODEL_FILTER_THRESHOLD;
  const filteredModels = modelFilter.trim()
    ? providerModels.filter((m) =>
        `${m.name} ${m.id}`.toLowerCase().includes(modelFilter.trim().toLowerCase()),
      )
    : providerModels;
  // Never drop the current selection from the rendered options (filtering is a
  // find-aid, not a constraint on what's selected).
  const renderedModels =
    model && !filteredModels.some((m) => m.id === model)
      ? [...(providerModels.filter((m) => m.id === model)), ...filteredModels]
      : filteredModels;

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
        cache_bust_probe: cacheBust,
        extra_request_headers,
        geo_hint: geoHint.trim() || null,
        investigate,
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
    <main className="page launch">
      <TopBar />
      <h1>Which layer serves this page?</h1>
      <p className="lede">
        Stratum requests the page a few times, traces the route, and a model reads the evidence.
      </p>

      <form onSubmit={handleSubmit} noValidate>
        <div className="url-row">
          <label className="sr-only" htmlFor="url">
            Page URL
          </label>
          <input
            id="url"
            className={urlError ? "url-input invalid" : "url-input"}
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
          <button type="submit" className="btn-primary" disabled={noProviders || submitting}>
            {submitting ? "Starting…" : "Analyze"}
          </button>
        </div>
        {urlError && (
          <span id="url-error" className="field-error" role="alert">
            {urlError}
          </span>
        )}
        {submitError && (
          <span className="field-error" role="alert">
            {submitError}
          </span>
        )}

        {noProviders ? (
          <p className="note launch-empty">
            No LLM providers configured. Set <code>ANTHROPIC_API_KEY</code> or{" "}
            <code>OPENROUTER_API_KEY</code> in the environment and reload.
          </p>
        ) : (
          <div className="model-row">
            <span>Read by</span>
            <label className="sr-only" htmlFor="provider">
              Provider
            </label>
            <select id="provider" className="quiet-select" value={provider} onChange={(e) => onProviderChange(e.target.value)}>
              {(providers ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="model">
              Model
            </label>
            {showModelFilter && (
              <input
                className="quiet-input"
                type="search"
                placeholder="filter models…"
                aria-label="Filter models"
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
              />
            )}
            <select
              id="model"
              className="quiet-select"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={modelsLoading && providerModels.length === 0}
            >
              {renderedModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            <span className="note" role="status">
              {modelsLoading ? "loading models…" : `${providerModels.length} available`}
            </span>
          </div>
        )}

        <details className="more-options">
          <summary>More options</summary>
          <div className="options-grid">
            <div className="field">
              <label className="field-label" htmlFor="request-count">
                Requests
              </label>
              <input id="request-count" className="quiet-input" type="number" min={1} max={20} value={requestCount} onChange={(e) => setRequestCount(e.target.value)} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="interval">
                Interval (ms)
              </label>
              <input id="interval" className="quiet-input" type="number" min={0} max={60000} value={intervalMs} onChange={(e) => setIntervalMs(e.target.value)} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="geo-hint">
                Geo hint
              </label>
              <input id="geo-hint" className="quiet-input" type="text" placeholder="optional, e.g. fra" value={geoHint} onChange={(e) => setGeoHint(e.target.value)} />
            </div>
          </div>
          <label className="check">
            <input type="checkbox" checked={warm} onChange={(e) => setWarm(e.target.checked)} />
            Warm the cache (browser navigation) before sampling
          </label>
          <label className="check">
            <input type="checkbox" checked={cacheBust} onChange={(e) => setCacheBust(e.target.checked)} />
            Cache-bust probe (forced miss)
          </label>
          <label className="check">
            <input type="checkbox" checked={investigate} onChange={(e) => setInvestigate(e.target.checked)} />
            Let the model investigate: up to 5 extra requests to this URL with headers it chooses
          </label>
          <div className="field">
            <span className="field-label">Custom request headers</span>
            {headers.map((row, i) => (
              <div key={i} className="header-row">
                <input className="quiet-input" aria-label={`header ${i + 1} name`} placeholder="Header-Name" value={row.name} onChange={(e) => updateHeader(i, { name: e.target.value })} />
                <input className="quiet-input" aria-label={`header ${i + 1} value`} placeholder="value" value={row.value} onChange={(e) => updateHeader(i, { value: e.target.value })} />
                <button type="button" className="btn-quiet" aria-label="add header row" onClick={() => setHeaders((r) => [...r, { name: "", value: "" }])}>
                  +
                </button>
              </div>
            ))}
          </div>
        </details>
      </form>

      {recent.length > 0 && (
        <section className="recent">
          <h2>Recent</h2>
          {recent.map((r) => {
            const running = isInProgress(r.status);
            const degraded = isDegraded(r.verdict_json) || r.status === "error";
            const verdict = degraded || running ? null : (r.verdict_json as unknown as CacheVerdict | null);
            return (
              <div key={r.id} className="recent-row">
                <span className={`vdot ${verdictDot(r)}`} aria-hidden="true" />
                <Link className="url" to={running ? `/runs/${r.id}` : `/reports/${r.id}`}>
                  {r.url}
                </Link>
                <span className="what">{running ? "Running…" : servedPhrase(verdict, degraded)}</span>
                <ConfidenceMeter level={verdict ? verdict.confidence : null} />
                <span className="when">{shortWhen(r.created_at)}</span>
              </div>
            );
          })}
        </section>
      )}
    </main>
  );
}

function verdictDot(r: Report): "hit" | "miss" | "unknown" {
  const v = r.verdict_json as unknown as CacheVerdict | null;
  if (!v || isDegraded(r.verdict_json) || r.status === "error") return "unknown";
  return v.cached ? "hit" : "miss";
}

function shortWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
