import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { deleteAnalysis, listAnalyses, type Report } from "../api/client";
import { ConfidenceMeter, TopBar } from "../components";
import { isInProgress, servedPhrase } from "./report/story";
import type { CacheVerdict, Finding } from "./report/types";
import { isDegraded } from "./report/types";

// History view (§8.1.4, 1.3.0 redesign). A quiet list — verdict dot, page,
// served-from phrase, the model's confidence, finding counts, time — with
// domain + has-critical filters
// mirrored to the URL (shareable), row → report permalink, and delete-with-
// confirm. Every row is a pure projection of the §6 report shape.
type Dot = "hit" | "miss" | "unknown";

interface RowView {
  id: string;
  url: string;
  href: string;
  createdLabel: string | null;
  dot: Dot;
  served: string;
  confidence: string | null;
  crit: number;
  warn: number;
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
  const running = isInProgress(report.status);
  const degraded = isDegraded(report.verdict_json) || report.status === "error";
  const verdict = degraded || running ? null : (report.verdict_json as unknown as CacheVerdict | null);
  let dot: Dot = "unknown";
  if (verdict) {
    if (verdict.provider === "UNKNOWN") dot = "unknown";
    else dot = verdict.cached ? "hit" : "miss";
  }
  const { crit, warn } = countFindings(report);
  return {
    id: report.id,
    url: report.url,
    href: running ? `/runs/${report.id}` : `/reports/${report.id}`,
    createdLabel: report.created_at
      ? new Date(report.created_at).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : null,
    dot,
    served: running ? "Running…" : servedPhrase(verdict, degraded),
    confidence: verdict?.confidence ?? null,
    crit,
    warn,
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
    <main className="page history">
      <TopBar />
      <h1>History</h1>

      <div className="hist-filters">
        <input
          className="quiet-box"
          type="search"
          placeholder="Filter by domain"
          aria-label="Filter by domain"
          value={domain}
          onChange={(e) => setFilter({ domain: e.target.value })}
        />
        <label className="check">
          <input type="checkbox" checked={critical} onChange={(e) => setFilter({ critical: e.target.checked })} />
          Only with critical findings
        </label>
      </div>

      {error && <p className="note">Could not load history: {error}</p>}

      {!error && reports !== null && rows.length === 0 && (
        <p className="empty-state" data-testid="history-empty">
          {domain || critical ? (
            <>No analyses match these filters. Clear them, or run a new analysis.</>
          ) : (
            <>
              No analyses yet. <Link to="/">Run your first one</Link> to see it here.
            </>
          )}
        </p>
      )}

      {rows.length > 0 && (
        <table className="hist-list" data-testid="history-table">
          <thead>
            <tr>
              <th aria-label="Verdict" />
              <th>Page</th>
              <th>Served from</th>
              <th>Confidence</th>
              <th>Findings</th>
              <th className="when">When</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="hist-row" onClick={() => navigate(r.href)}>
                <td>
                  <span className={`vdot ${r.dot}`} title={DOT_TITLE[r.dot]} data-dot={r.dot} />
                </td>
                <td className="url">
                  <Link to={r.href} onClick={(e) => e.stopPropagation()}>
                    {r.url}
                  </Link>
                </td>
                <td className="what">{r.served}</td>
                <td>
                  <ConfidenceMeter level={r.confidence} />
                </td>
                <td className="hist-find">
                  {r.crit === 0 && r.warn === 0 ? (
                    <span className="none">none</span>
                  ) : (
                    <>
                      {r.crit > 0 && <span className="fc crit">{r.crit} critical</span>}
                      {r.warn > 0 && <span className="fc warn">{r.warn} {r.warn === 1 ? "warning" : "warnings"}</span>}
                    </>
                  )}
                </td>
                <td className="when">{r.createdLabel ?? "—"}</td>
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
      )}
    </main>
  );
}
