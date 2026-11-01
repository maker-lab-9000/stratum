import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { getReport, rerunAnalysis, type Report } from "../../api/client";
import { TopBar } from "../../components";
import { Answer } from "./Answer";
import { Claims } from "./Claims";
import { Findings, timingCard } from "./Findings";
import { Hosted } from "./Hosted";
import { Progression } from "./Progression";
import { Strata } from "./Strata";
import { edgeRttMs, splitSamples } from "./timing";
import type { CacheVerdict, Finding, RawSample } from "./types";
import { isDegraded } from "./types";

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
      <main className="page">
        <div className="empty-state">Could not load this report: {error}</div>
      </main>
    );
  }
  if (!report) {
    return (
      <main className="page">
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

  const verdict = isDegraded(report.verdict_json) ? null : (report.verdict_json as unknown as CacheVerdict | null);
  const showStory = report.status !== "error" && verdict !== null && Array.isArray(verdict.layers);
  const samples = (report.samples_json as unknown as RawSample[] | null) ?? [];
  const { requests, probe } = splitSamples(samples);
  const edgeRtt = edgeRttMs(requests);
  const security = (report.llm_json?.["security_findings"] as Finding[] | undefined) ?? [];
  const performance = (report.llm_json?.["performance_findings"] as Finding[] | undefined) ?? [];

  return (
    <main className="page">
      <TopBar
        context={
          <>
            <span className="url" title={report.url}>
              {report.url}
            </span>
            {report.model && <span>read by {report.model}</span>}
            {createdLabel && <span>{createdLabel}</span>}
          </>
        }
        actions={
          <button type="button" className="btn-quiet" onClick={onRerun}>
            Re-run
          </button>
        }
      />

      <Answer report={report} onRerun={onRerun} />
      {showStory && verdict && (
        <>
          <Strata verdict={verdict} vantage={report.vantage} />
          <Claims verdict={verdict} />
        </>
      )}

      {requests.length > 0 && (
        <section>
          <h2>What the requests showed</h2>
          <p className="lede">
            Measured values from {requests.length} consecutive requests
            {probe ? ", plus one with a random query string to force a miss." : "."}
            {verdict ? " The first row is the model's reading." : ""}
          </p>
          <Progression verdict={verdict} samples={samples} />
          {edgeRtt != null && <p className="note">One round trip to the edge took {edgeRtt} ms.</p>}
        </section>
      )}

      {verdict && (security.length > 0 || performance.length > 0 || timingCard(verdict.timing_check)) && (
        <section>
          <h2>What to look at</h2>
          <Findings security={security} performance={performance} timing={verdict.timing_check} />
        </section>
      )}

      <Hosted report={report} />

      <p className="note footnote">
        Measurements (DNS, headers, timing, traceroute) are facts. The verdict is the model's reading
        of them, and every claim's cited evidence is checked against the captured data.
      </p>
    </main>
  );
}
