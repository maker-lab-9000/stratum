import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getReport, rerunAnalysis, type Report } from "../../api/client";
import { Badge } from "../../components";
import { Section01 } from "./Section01";
import { VerdictTiles } from "./VerdictTiles";

// The report centerpiece. Loads by id (or renders an injected report, used by the
// /dev/report demo and tests). Section 02 + findings land in T19.
interface ReportViewProps {
  report?: Report;
}

export function ReportView({ report: injected }: ReportViewProps) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState<Report | null>(injected ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (injected || !id) return;
    getReport(id)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load report"));
  }, [id, injected]);

  async function onRerun() {
    if (!report) return;
    const { id: newId } = await rerunAnalysis(report.id);
    navigate(`/runs/${newId}`);
  }

  if (error) {
    return (
      <main className="wrap" style={{ paddingTop: 40 }}>
        <div className="empty-state">Could not load this report: {error}</div>
      </main>
    );
  }
  if (!report) {
    return (
      <main className="wrap" style={{ paddingTop: 40 }}>
        <div className="empty-state">Loading report…</div>
      </main>
    );
  }

  const createdLabel = report.created_at
    ? new Date(report.created_at).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="dot" />
            <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
              Stratum
            </Link>
            <span className="sub">cache analysis</span>
          </div>
          <div className="target">
            <span className="url" title={report.url}>
              {report.url}
            </span>
          </div>
          <div className="meta-pills">
            {report.model && (
              <Badge variant="pill" keep>
                Model <b>{report.model}</b>
              </Badge>
            )}
            {report.samples_json && (
              <Badge variant="pill">{report.samples_json.length} requests</Badge>
            )}
            {createdLabel && <Badge variant="pill">{createdLabel}</Badge>}
          </div>
          <button type="button" className="btn" onClick={onRerun}>
            Re-run
          </button>
        </div>
      </header>

      <main className="wrap">
        <VerdictTiles report={report} onRerun={onRerun} />
        <Section01 report={report} />

        {/* Section 02 (serving layer + findings + raw drawer) lands in T19. */}

        <p className="footnote">
          Measurements (DNS, headers, traceroute) are ground-truth facts. The verdict is
          interpreted from them by the LLM, with every claim's evidence citation machine-checked
          against the captured data.
        </p>
      </main>
    </>
  );
}
