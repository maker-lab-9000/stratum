import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { deleteAnalysis, listAnalyses, type Report } from "../api/client";
import type { CacheVerdict, Finding } from "./report/types";
import { isDegraded } from "./report/types";

// History view (§8.1.4). A dense table — verdict dot, URL, serving layer, layer
// count, finding counts, model, time — with domain + has-critical filters
// mirrored to the URL (shareable), row → report permalink, and delete-with-
// confirm. Every row is a pure projection of the §6 report shape.
type Dot = "hit" | "miss" | "unknown";

interface RowView {
  id: string;
  url: string;
  model: string | null;
  createdLabel: string | null;
  dot: Dot;
  servingLayer: string | null;
  layerCount: number | null;
  crit: number;
  warn: number;
  info: number;
}

function countFindings(report: Report): { crit: number; warn: number; info: number } {
  const llm = report.llm_json ?? {};
  const findings = [
    ...((llm["security_findings"] as Finding[] | undefined) ?? []),
    ...((llm["performance_findings"] as Finding[] | undefined) ?? []),
  ];
  let crit = 0;
  let warn = 0;
  let info = 0;
  for (const f of findings) {
    if (f.severity === "critical") crit++;
    else if (f.severity === "warning") warn++;
    else if (f.severity === "info") info++;
  }
  return { crit, warn, info };
}

// The cached-verdict dot: green only for a genuine cache hit; neutral for a
// bypass (served, but not from cache); dashed grey when the verdict is degraded
// or the provider/state is UNKNOWN (§8.3 — grey, never green/amber).
function toRow(report: Report): RowView {
  const degraded = isDegraded(report.verdict_json);
  const verdict = degraded ? null : (report.verdict_json as unknown as CacheVerdict | null);
  let dot: Dot = "unknown";
  if (verdict) {
    if (verdict.provider === "UNKNOWN") dot = "unknown";
    else dot = verdict.cached ? "hit" : "miss";
  }
  const { crit, warn, info } = countFindings(report);
  return {
    id: report.id,
    url: report.url,
    model: report.model,
    createdLabel: report.created_at
      ? new Date(report.created_at).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : null,
    dot,
    servingLayer: verdict?.serving_layer ?? null,
    layerCount: verdict?.layer_count_to_origin ?? null,
    crit,
    warn,
    info,
  };
}

const DOT_TITLE: Record<Dot, string> = {
  hit: "Served from cache",
  miss: "Not cached (bypass / origin)",
  unknown: "Verdict unknown or degraded",
};

export function History() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const domain = params.get("domain") ?? "";
  const critical = params.get("critical") === "1";

  const [reports, setReports] = useState<Report[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    listAnalyses({ domain: domain || null, hasCritical: critical })
      .then((r) => setReports(r.reports))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load history"));
  }, [domain, critical]);

  useEffect(() => {
    load();
  }, [load]);

  // Filters write straight to the URL query so a filtered view is shareable and
  // survives refresh; changing them refetches via the effect above.
  function setFilter(next: { domain?: string; critical?: boolean }) {
    const p = new URLSearchParams(params);
    if (next.domain !== undefined) {
      if (next.domain) p.set("domain", next.domain);
      else p.delete("domain");
    }
    if (next.critical !== undefined) {
      if (next.critical) p.set("critical", "1");
      else p.delete("critical");
    }
    setParams(p, { replace: true });
  }

  async function onDelete(id: string) {
    try {
      await deleteAnalysis(id);
      setReports((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setConfirmingId(null);
    }
  }

  const rows = reports?.map(toRow) ?? [];

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="dot" />
            <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
              Stratum
            </Link>
            <span className="sub">history</span>
          </div>
          <div className="target" />
          <Link to="/" className="btn">
            New analysis
          </Link>
        </div>
      </header>

      <main className="wrap" style={{ paddingTop: 28 }}>
        <div className="eyebrow">
          <span className="step">▤</span> Past analyses
        </div>

        <div className="hist-filters">
          <input
            className="input"
            type="search"
            placeholder="Filter by domain…"
            aria-label="Filter by domain"
            value={domain}
            onChange={(e) => setFilter({ domain: e.target.value })}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={critical}
              onChange={(e) => setFilter({ critical: e.target.checked })}
            />
            Has critical findings
          </label>
        </div>

        {error && <div className="empty-state">Could not load history: {error}</div>}

        {!error && reports !== null && rows.length === 0 && (
          <div className="empty-state" data-testid="history-empty">
            {domain || critical ? (
              <>No analyses match these filters. Clear them, or run a new analysis.</>
            ) : (
              <>
                No analyses yet. <Link to="/">Run your first one</Link> to see it here.
              </>
            )}
          </div>
        )}

        {rows.length > 0 && (
          <div className="tbl-wrap">
            <table className="hist" data-testid="history-table">
              <thead>
                <tr>
                  <th aria-label="Verdict" />
                  <th>URL</th>
                  <th>Serving layer</th>
                  <th>Layers</th>
                  <th>Findings</th>
                  <th>Model</th>
                  <th>When</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="hist-row" onClick={() => navigate(`/reports/${r.id}`)}>
                    <td>
                      <span className={`vdot ${r.dot}`} title={DOT_TITLE[r.dot]} data-dot={r.dot} />
                    </td>
                    <td className="hist-url">
                      <Link to={`/reports/${r.id}`} onClick={(e) => e.stopPropagation()}>
                        {r.url}
                      </Link>
                    </td>
                    <td>{r.servingLayer ?? "—"}</td>
                    <td>{r.layerCount ?? "—"}</td>
                    <td className="hist-find">
                      {r.crit === 0 && r.warn === 0 && r.info === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        <>
                          {r.crit > 0 && <span className="fc crit">{r.crit} critical</span>}
                          {r.warn > 0 && <span className="fc warn">{r.warn} warn</span>}
                          {r.info > 0 && <span className="fc info">{r.info} info</span>}
                        </>
                      )}
                    </td>
                    <td className="hist-model">{r.model ?? "—"}</td>
                    <td className="hist-when">{r.createdLabel ?? "—"}</td>
                    <td className="hist-actions" onClick={(e) => e.stopPropagation()}>
                      {confirmingId === r.id ? (
                        <span className="confirm">
                          Delete?
                          <button type="button" className="link-btn danger" onClick={() => onDelete(r.id)}>
                            Yes
                          </button>
                          <button type="button" className="link-btn" onClick={() => setConfirmingId(null)}>
                            No
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="link-btn"
                          aria-label={`Delete analysis for ${r.url}`}
                          onClick={() => setConfirmingId(r.id)}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}
