import { Fragment, useEffect, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { cancelAnalysis, getReport, subscribeAnalysis, type StreamEvent } from "../api/client";
import { TopBar } from "../components";
import { splitSamples } from "./report/timing";
import type { Dns, Hop, RawSample } from "./report/types";

// Live run (§8.1.2, 1.3.0 redesign): the same vertical spine as the report,
// filling in step by step from the SSE stream. Each finished step shows its key
// measurement inline (verbatim data only); raw headers are one disclosure away.
// The reducer is idempotent so a dropped-then-replayed stream (subscribeAnalysis
// reconnects) recovers without a stuck spinner. Terminal event → the report.
type StepStatus = "pending" | "active" | "done" | "failed";

// 1.4.0: the latest investigate-mode tool call, as the backend emitted it.
interface InvestigateCall {
  n: number;
  reason?: string;
  header_names?: string[];
  status_code?: number | null;
  refused?: string | null;
}

interface LiveState {
  stages: Record<string, StepStatus>;
  investigate: { last: InvestigateCall | null; count: number | null; seen: boolean };
  dns: Dns | null;
  warm: { warmed?: boolean; skipped?: boolean; error?: string | null; timing?: { duration_ms?: number } | null } | null;
  samples: RawSample[] | null;
  trace: { hops?: Hop[]; error?: unknown } | null;
  reconnecting: boolean;
  done: boolean;
}

const INITIAL: LiveState = {
  stages: { dns: "pending", warm: "pending", sample: "pending", traceroute: "pending", analyze: "pending" },
  investigate: { last: null, count: null, seen: false },
  dns: null,
  warm: null,
  samples: null,
  trace: null,
  reconnecting: false,
  done: false,
};

// Backend status → step status. "started" never regresses a finished step's
// data (keeps replay idempotent).
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
  const data = e.data as unknown;
  if (e.stage === "dns" && data && typeof data === "object") next.dns = data as Dns;
  if (e.stage === "warm" && data && typeof data === "object") next.warm = data as LiveState["warm"];
  if (e.stage === "sample" && Array.isArray(data)) next.samples = data as RawSample[];
  if (e.stage === "traceroute" && data && typeof data === "object") next.trace = data as LiveState["trace"];
  if (e.stage === "investigate") {
    if (e.status === "progress" && data && typeof data === "object") {
      next.investigate = { ...next.investigate, seen: true, last: data as InvestigateCall };
    } else if (e.status === "completed") {
      const count = (data as { count?: number } | undefined)?.count ?? next.investigate.count;
      // A run with no calls (or a provider without tools) shows no step.
      const seen = next.investigate.seen || (typeof count === "number" && count > 0);
      next.investigate = { ...next.investigate, seen, count: typeof count === "number" ? count : null };
    }
  }
  if (e.stage === "pipeline" && e.terminal) next.done = true;
  return next;
}

function errorText(err: unknown): string {
  if (!err) return "";
  if (typeof err === "string") return err;
  if (typeof err === "object" && "message" in err) return String((err as { message: unknown }).message);
  return "failed";
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

const header = (s: RawSample, name: string) =>
  s.headers.find(([k]) => k.toLowerCase() === name)?.[1] ?? null;

interface Step {
  id: string;
  name: string;
  status: StepStatus;
  out: string;
}

function buildSteps(state: LiveState, requestCount: number | null, model: string | null): Step[] {
  const { requests, probe } = splitSamples(state.samples ?? []);
  const n = requestCount ?? (state.samples ? requests.length : null);

  const chain = state.dns?.cname_chain ?? [];
  const addresses = (state.dns?.a?.length ?? 0) + (state.dns?.aaaa?.length ?? 0);
  const dnsOut = state.dns && (chain.length || addresses)
    ? `${chain.length ? chain[chain.length - 1].cname : (state.dns.a?.[0] ?? "")}, ${plural(addresses, "address", "addresses")}`
    : "";

  const warm = state.warm;
  const warmOut = !warm
    ? ""
    : warm.skipped
      ? "Skipped"
      : warm.warmed
        ? `Loaded in a browser${warm.timing?.duration_ms != null ? `, ${(warm.timing.duration_ms / 1000).toFixed(1)} s` : ""}`
        : errorText(warm.error);

  // 1.3.1: an Age header absent on every request says so in words, never "Age — → —".
  const ages = requests.map((s) => header(s, "age"));
  const ageOut = ages.some((a) => a !== null)
    ? `Age ${ages[0] ?? "—"} → ${ages[ages.length - 1] ?? "—"}`
    : "no Age header";
  const reqOut = requests.length ? `status ${requests[0].status ?? "—"}, ${ageOut}` : "";
  const probeAge = probe ? header(probe, "age") : null;
  const probeOut = probe
    ? [
        `status ${probe.status ?? "—"}`,
        ...(probeAge !== null ? [`Age ${probeAge}`] : []),
        `${probe.timing?.ttfb_ms ?? "—"} ms to first byte`,
      ].join(", ")
    : "";

  const hops = state.trace?.hops ?? [];
  const responsive = hops.filter((h) => !h.unresponsive && h.ip);
  const traceOut = state.stages.traceroute === "failed"
    ? errorText(state.trace?.error) || "Failed"
    : hops.length
      ? `${plural(hops.length, "hop", "hops")}, last ${responsive[responsive.length - 1]?.ip ?? "—"}`
      : "";

  const responses = (state.samples ?? []).length;
  const readOut = state.stages.analyze === "active"
    ? `${model ?? "The model"} is reading ${responses} responses…`
    : "";

  // 1.4.0: present only once the model has asked for something. Active while
  // calls arrive; done when the backend says how many it made.
  const inv = state.investigate;
  const invDone = inv.count !== null;
  const invOut = invDone
    ? `${inv.count} ${inv.count === 1 ? "request" : "requests"}`
    : inv.last
      ? `${inv.last.n} of 5: ${
          inv.last.refused
            ? `refused: ${inv.last.refused}`
            : `${(inv.last.header_names ?? []).join(", ") || "no extra headers"} · ${inv.last.status_code ?? "no response"}`
        }`
      : "";

  return [
    { id: "dns", name: "Look up DNS", status: state.stages.dns, out: dnsOut },
    { id: "warm", name: "Warm the cache", status: state.stages.warm, out: warmOut },
    { id: "sample", name: n != null ? `Request the page ${n}×` : "Request the page", status: state.stages.sample, out: reqOut },
    ...(probe ? [{ id: "probe", name: "Force a miss", status: state.stages.sample, out: probeOut }] : []),
    { id: "traceroute", name: "Trace the route", status: state.stages.traceroute, out: traceOut },
    { id: "analyze", name: "Read the evidence", status: state.stages.analyze, out: readOut },
    ...(inv.seen ? [{ id: "investigate", name: "Investigate", status: (invDone ? "done" : "active") as StepStatus, out: invOut }] : []),
  ];
}

export function LiveRun() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const requestCount = (location.state as { requestCount?: number } | null)?.requestCount ?? null;
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [meta, setMeta] = useState<{ url: string | null; model: string | null }>({ url: null, model: null });
  const navigatedRef = useRef(false);

  useEffect(() => {
    if (!id) return;
    const close = subscribeAnalysis(id, {
      onEvent: (event) => dispatch({ type: "event", event }),
      onError: () => dispatch({ type: "reconnecting" }),
    });
    return close;
  }, [id]);

  // URL + model for the top bar and the "reading" line (works after a reload,
  // when there's no router state).
  useEffect(() => {
    if (!id) return;
    getReport(id)
      .then((r) => setMeta({ url: r.url ?? null, model: r.model ?? null }))
      .catch(() => undefined);
  }, [id]);

  useEffect(() => {
    if (state.done && id && !navigatedRef.current) {
      navigatedRef.current = true;
      navigate(`/reports/${id}`, { replace: true });
    }
  }, [state.done, id, navigate]);

  async function onCancel() {
    if (!id) return;
    try {
      await cancelAnalysis(id);
    } finally {
      if (!navigatedRef.current) {
        navigatedRef.current = true;
        navigate(`/reports/${id}`, { replace: true });
      }
    }
  }

  const steps = buildSteps(state, requestCount, meta.model);
  const first = state.samples?.find((s) => !s.probe) ?? null;

  return (
    <main className="page live">
      <TopBar
        context={meta.url ? <span className="url">{meta.url}</span> : undefined}
        actions={
          !state.done && (
            <button type="button" className="btn-quiet" onClick={onCancel}>
              Cancel
            </button>
          )
        }
      />
      <h1>Analyzing…</h1>
      <p className="lede">Measurements appear as they land. The model reads them at the end.</p>

      <ol className="steps" data-testid="stepper" aria-label="Analysis progress">
        {steps.map((s) => (
          <li key={s.id} className={`step is-${s.status}`} aria-current={s.status === "active" ? "step" : undefined}>
            <span className="step-mark" aria-hidden="true" />
            <span className="step-name">{s.name}</span>
            <span className="step-out">
              {s.out}
              {s.id === "sample" && first && (
                <details className="raw-peek">
                  <summary>Show raw headers</summary>
                  <pre className="raw">
                    {[first.http_version, first.status].filter((x) => x != null).join(" ") + "\n"}
                    {first.headers.map(([k, v], i) => (
                      <Fragment key={i}>
                        <span className="hk">{k}</span>: <span className="hv">{v}</span>
                        {"\n"}
                      </Fragment>
                    ))}
                  </pre>
                </details>
              )}
            </span>
          </li>
        ))}
      </ol>

      {state.reconnecting && (
        <p className="note" role="status">
          Connection dropped, reconnecting…
        </p>
      )}
    </main>
  );
}
