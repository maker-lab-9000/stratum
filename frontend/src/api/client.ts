// Typed client for the Stratum API (spec §7). Single-origin: paths are relative
// so the Vite dev proxy / prod static host route them to the backend.

export interface ModelInfo {
  id: string;
  name: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: ModelInfo[];
}

export interface AnalysisOptions {
  request_count: number;
  interval_ms: number;
  warm: boolean;
  extra_request_headers: Record<string, string>;
  geo_hint: string | null;
}

export interface CreateAnalysisBody {
  url: string;
  provider: string;
  model: string;
  options: AnalysisOptions;
}

/** A report as returned by GET /api/analyses/:id (Report.as_dict, §6). */
export interface Report {
  id: string;
  url: string;
  created_at: string | null;
  status: "queued" | "running" | "done" | "error";
  provider: string | null;
  model: string | null;
  vantage: string | null;
  verdict_json: Record<string, unknown> | null;
  dns_json: Record<string, unknown> | null;
  traceroute_json: Record<string, unknown> | null;
  samples_json: unknown[] | null;
  llm_json: Record<string, unknown> | null;
  error: string | null;
  domain: string;
  has_critical: boolean;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function getModels(): Promise<{ providers: ProviderInfo[] }> {
  return json(await fetch("/api/models"));
}

/** Live model list for one provider (fetched on demand; server falls back to
 * the provider's static list on any upstream error). */
export async function getProviderModels(
  provider: string,
): Promise<{ provider: string; models: ModelInfo[] }> {
  return json(await fetch(`/api/models/${encodeURIComponent(provider)}`));
}

export async function createAnalysis(body: CreateAnalysisBody): Promise<{ id: string }> {
  return json(
    await fetch("/api/analyses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function getReport(id: string): Promise<Report> {
  return json(await fetch(`/api/analyses/${id}`));
}

export interface ListFilters {
  domain?: string | null;
  hasCritical?: boolean;
}

/** GET /api/analyses with optional domain + has-critical filters (§7 history). */
export async function listAnalyses(filters: ListFilters = {}): Promise<{ reports: Report[] }> {
  const params = new URLSearchParams();
  if (filters.domain) params.set("domain", filters.domain);
  if (filters.hasCritical) params.set("has_critical", "true");
  const qs = params.toString();
  return json(await fetch(`/api/analyses${qs ? `?${qs}` : ""}`));
}

export async function deleteAnalysis(id: string): Promise<void> {
  const res = await fetch(`/api/analyses/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
}

export async function rerunAnalysis(id: string): Promise<{ id: string }> {
  return json(await fetch(`/api/analyses/${id}/rerun`, { method: "POST" }));
}

export function streamUrl(id: string): string {
  return `/api/analyses/${id}/stream`;
}

/** One progress event off the SSE stream (backend orchestrator, §3). */
export interface StreamEvent {
  stage: string;
  status?: string;
  terminal?: boolean;
  degraded?: boolean;
  data?: unknown;
  error?: string;
  gaps?: unknown;
  report?: Report;
  seq?: number;
  ts?: number;
}

export interface StreamHandlers {
  onEvent: (event: StreamEvent) => void;
  /** Called when a connection drops before a terminal event; a reconnect follows. */
  onError?: (err: unknown) => void;
}

interface SubscribeOptions {
  reconnectDelayMs?: number;
}

// Consume the analysis SSE stream via fetch + ReadableStream (works behind the
// dev proxy and is straightforward to mock). On a drop before the terminal
// event it reconnects; the backend replays buffered history on re-subscribe, so
// the caller's reducer recovers full state (must be idempotent per event).
// Returns a closer that aborts the connection and stops reconnecting.
export function subscribeAnalysis(
  id: string,
  handlers: StreamHandlers,
  options: SubscribeOptions = {},
): () => void {
  const reconnectDelayMs = options.reconnectDelayMs ?? 800;
  let closed = false;
  let controller: AbortController | null = null;

  async function run() {
    while (!closed) {
      controller = new AbortController();
      let sawTerminal = false;
      try {
        const res = await fetch(streamUrl(id), {
          headers: { accept: "text/event-stream" },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            const line = frame.split("\n").find((l) => l.startsWith("data:"));
            if (!line) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            let event: StreamEvent;
            try {
              event = JSON.parse(payload) as StreamEvent;
            } catch {
              continue;
            }
            if (closed) return;
            handlers.onEvent(event);
            if (event.terminal) sawTerminal = true;
          }
        }
      } catch {
        if (closed) return;
      }
      if (sawTerminal || closed) return;
      // Dropped before the terminal event (network error or a clean close mid-run):
      // signal it, back off, then reconnect. The backend replays buffered history
      // on re-subscribe, so an idempotent reducer recovers full state.
      handlers.onError?.(new Error("stream dropped"));
      await new Promise((r) => setTimeout(r, reconnectDelayMs));
    }
  }

  void run();
  return () => {
    closed = true;
    controller?.abort();
  };
}
