import { useEffect, useReducer, useRef } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { subscribeAnalysis, type StreamEvent } from "../api/client";
import type { Hop } from "./report/types";

// Live run view (§8.1.2). A horizontal stepper — Resolve DNS → Warm →
// Request 1…N → Traceroute → Analyze — driven by the SSE stream; raw headers and
// hops render as they land, before the LLM runs. On the terminal event it hands
// off to the report. The reducer is idempotent so a dropped-then-replayed stream
// (subscribeAnalysis reconnects) recovers state without a stuck spinner.
type StepStatus = "pending" | "active" | "done" | "failed";

interface Sample {
  request: number;
  http_version?: string;
  status?: number;
  headers: [string, string][];
}

interface LiveState {
  stages: Record<string, StepStatus>;
  samples: Sample[] | null;
  hops: Hop[] | null;
  reconnecting: boolean;
  done: boolean;
}

const INITIAL: LiveState = {
  stages: { dns: "pending", warm: "pending", sample: "pending", traceroute: "pending", analyze: "pending" },
  samples: null,
  hops: null,
  reconnecting: false,
  done: false,
};

// Backend status → step status. Unknown/"started" transitions never regress a
// step that already finished (keeps replay idempotent).
function mapStatus(status: string | undefined): StepStatus | null {
  if (status === "started") return "active";
  if (status === "completed" || status === "degraded") return "done";
  if (status === "failed") return "failed";
  return null;
}

type Action = { type: "event"; event: StreamEvent } | { type: "reconnecting" };

function reducer(state: LiveState, action: Action): LiveState {
  if (action.type === "reconnecting") return { ...state, reconnecting: true };
  const e = action.event;
  const next: LiveState = { ...state, stages: { ...state.stages }, reconnecting: false };

  if (e.stage in next.stages) {
    const mapped = mapStatus(e.status);
    if (mapped) next.stages[e.stage] = mapped;
  }
  if (e.stage === "sample" && Array.isArray(e.data)) next.samples = e.data as Sample[];
  if (e.stage === "traceroute" && e.data && typeof e.data === "object") {
    const hops = (e.data as { hops?: Hop[] }).hops;
    if (Array.isArray(hops)) next.hops = hops;
  }
  if (e.stage === "pipeline" && e.terminal) next.done = true;
  return next;
}

interface Step {
  id: string;
  label: string;
  status: StepStatus;
}

// The canonical stepper order (§8.1.2). Request 1…N expand from the known count
// (passed via router state on launch), else a single "Requests" step until the
// sample event reveals N.
function buildSteps(state: LiveState, requestCount: number | null): Step[] {
  const sample = state.stages.sample;
  const n = requestCount ?? state.samples?.length ?? null;
  const requestSteps: Step[] =
    n != null
      ? Array.from({ length: n }, (_, i) => ({ id: `req-${i + 1}`, label: `Request ${i + 1}`, status: sample }))
      : [{ id: "requests", label: "Requests", status: sample }];
  return [
    { id: "dns", label: "Resolve DNS", status: state.stages.dns },
    { id: "warm", label: "Warm", status: state.stages.warm },
    ...requestSteps,
    { id: "traceroute", label: "Traceroute", status: state.stages.traceroute },
    { id: "analyze", label: "Analyze", status: state.stages.analyze },
  ];
}

export function LiveRun() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const requestCount = (location.state as { requestCount?: number } | null)?.requestCount ?? null;
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const navigatedRef = useRef(false);

  useEffect(() => {
    if (!id) return;
    const close = subscribeAnalysis(id, {
      onEvent: (event) => dispatch({ type: "event", event }),
      onError: () => dispatch({ type: "reconnecting" }),
    });
    return close;
  }, [id]);

  // Hand off to the report once the pipeline terminates (done, degraded, or
  // error — the report view renders each state).
  useEffect(() => {
    if (state.done && id && !navigatedRef.current) {
      navigatedRef.current = true;
      navigate(`/reports/${id}`, { replace: true });
    }
  }, [state.done, id, navigate]);

  const steps = buildSteps(state, requestCount);
  const analyzing = state.stages.analyze === "active";

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="dot" />
            <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
              Stratum
            </Link>
            <span className="sub">live run</span>
          </div>
          <div className="target">
            <span className="url">Analysis {id}</span>
          </div>
        </div>
      </header>

      <main className="wrap" style={{ paddingTop: 28 }}>
        <div className="eyebrow">
          <span className="step">▶</span> Collecting evidence
        </div>

        <ol className="stepper" data-testid="stepper" aria-label="Analysis progress">
          {steps.map((s) => (
            <li
              key={s.id}
              className={`stp is-${s.status}`}
              aria-current={s.status === "active" ? "step" : undefined}
            >
              <span className="stp-dot" aria-hidden="true">
                {s.status === "done" ? "✓" : s.status === "failed" ? "✕" : ""}
              </span>
              <span className="stp-label">{s.label}</span>
            </li>
          ))}
        </ol>

        {state.reconnecting && (
          <p className="live-note" role="status">
            Connection dropped — reconnecting…
          </p>
        )}

        <div className="live-grid">
          {state.samples && state.samples.length > 0 && (
            <section className="live-panel" data-testid="live-headers">
              <div className="eyebrow sub">Raw headers · request 1</div>
              <pre className="raw">
                {[state.samples[0].http_version, state.samples[0].status].filter(Boolean).join(" ") + "\n"}
                {state.samples[0].headers.map(([k, v], i) => (
                  <span key={i}>
                    <span className="hk">{k}</span>: <span className="hv">{v}</span>
                    {"\n"}
                  </span>
                ))}
              </pre>
            </section>
          )}

          {state.hops && state.hops.length > 0 && (
            <section className="live-panel" data-testid="live-hops">
              <div className="eyebrow sub">Traceroute · {state.hops.length} hops</div>
              <ul className="live-hops">
                {state.hops.map((h) => (
                  <li key={h.n}>
                    <span className="hn">{h.n}</span>
                    <span className="hip">{h.unresponsive ? "* * *" : h.ip}</span>
                    <span className="horg">{h.org ?? (h.private ? "private" : "")}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <p className="live-note" role="status">
          {analyzing
            ? "Evidence collected — the model is interpreting it…"
            : state.done
              ? "Done — opening the report…"
              : "Measurements stream in as each stage lands; the verdict runs last."}
        </p>
      </main>
    </>
  );
}
