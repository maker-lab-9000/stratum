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

export async function rerunAnalysis(id: string): Promise<{ id: string }> {
  return json(await fetch(`/api/analyses/${id}/rerun`, { method: "POST" }));
}

export function streamUrl(id: string): string {
  return `/api/analyses/${id}/stream`;
}
