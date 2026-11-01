import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

import type { StreamEvent, StreamHandlers } from "../api/client";
import { cancelAnalysis, getReport, subscribeAnalysis } from "../api/client";
import { LiveRun } from "./LiveRun";

// Capture the handlers the component registers so the test can drive the stream.
let handlers: StreamHandlers;
const closeMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("../api/client", () => ({
  subscribeAnalysis: vi.fn((_id: string, h: StreamHandlers) => {
    handlers = h;
    return closeMock;
  }),
  getReport: vi.fn(),
  cancelAnalysis: vi.fn(),
}));
vi.mock("react-router-dom", async (orig) => {
  const actual = (await orig()) as object;
  return { ...actual, useNavigate: () => navigateMock };
});

beforeEach(() => {
  navigateMock.mockReset();
  closeMock.mockReset();
  vi.mocked(subscribeAnalysis).mockClear();
  vi.mocked(getReport).mockReset().mockResolvedValue({
    id: "rep-1", url: "https://www.persil.de/", model: "claude-opus-4-8",
  } as never);
  vi.mocked(cancelAnalysis).mockReset().mockResolvedValue({ id: "rep-1", status: "error" });
});

function renderRun(requestCount?: number) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/runs/rep-1", state: requestCount ? { requestCount } : undefined }]}>
      <Routes>
        <Route path="/runs/:id" element={<LiveRun />} />
      </Routes>
    </MemoryRouter>,
  );
}

const emit = (event: StreamEvent) => act(() => handlers.onEvent(event));
function step(label: string | RegExp) {
  return screen.getByText(label).closest(".step") as HTMLElement;
}

const sample = (request: number, age: number, extra: Record<string, unknown> = {}) => ({
  request,
  ok: true,
  status: 200,
  http_version: "HTTP/2",
  headers: [["age", String(age)], ["x-cache", "MISS"]],
  timing: { connect_ms: null, tls_ms: null, ttfb_ms: 40 + request, total_ms: 50, rtt_ms: null },
  ...extra,
});

test("steps in order; N from router state; forced miss only when the probe arrives", () => {
  renderRun(3);
  const labels = Array.from(screen.getByTestId("stepper").querySelectorAll(".step-name")).map((n) => n.textContent);
  expect(labels).toEqual(["Look up DNS", "Warm the cache", "Request the page 3×", "Trace the route", "Read the evidence"]);

  emit({ stage: "sample", status: "completed", data: [sample(1, 0), sample(2, 5), sample(3, 9), { ...sample(4, 0), probe: "cache_bust" }] });
  const after = Array.from(screen.getByTestId("stepper").querySelectorAll(".step-name")).map((n) => n.textContent);
  expect(after).toEqual(["Look up DNS", "Warm the cache", "Request the page 3×", "Force a miss", "Trace the route", "Read the evidence"]);
});

test("without router state, the request count comes from samples minus the probe", () => {
  renderRun();
  expect(step("Request the page")).toBeInTheDocument();
  emit({ stage: "sample", status: "completed", data: [sample(1, 0), sample(2, 0), sample(3, 0), sample(4, 0), { ...sample(5, 0), probe: "cache_bust" }] });
  expect(step("Request the page 4×")).toBeInTheDocument();
});

test("events advance the steps", () => {
  renderRun(2);
  emit({ stage: "dns", status: "started" });
  expect(step("Look up DNS")).toHaveClass("is-active");
  emit({ stage: "dns", status: "completed", data: { a: ["1.1.1.1", "1.1.1.2"], aaaa: [], cname_chain: [{ name: "www.x", cname: "e1.cdn.net", ttl: 20 }] } });
  expect(step("Look up DNS")).toHaveClass("is-done");
  emit({ stage: "sample", status: "started" });
  expect(step("Request the page 2×")).toHaveClass("is-active");
  emit({ stage: "analyze", status: "started" });
  expect(step("Read the evidence")).toHaveClass("is-active");
});

test("inline measurements from verbatim data", async () => {
  renderRun(3);
  await waitFor(() => expect(getReport).toHaveBeenCalledWith("rep-1"));
  emit({ stage: "dns", status: "completed", data: { a: ["1.1.1.1", "1.1.1.2"], aaaa: [], cname_chain: [{ name: "www.x", cname: "e1.cdn.net", ttl: 20 }] } });
  expect(step("Look up DNS").textContent).toContain("e1.cdn.net, 2 addresses");
  emit({ stage: "warm", status: "completed", data: { warmed: true, skipped: false, timing: { duration_ms: 1234 } } });
  expect(step("Warm the cache").textContent).toContain("Loaded in a browser, 1.2 s");
  emit({ stage: "sample", status: "completed", data: [sample(1, 0), sample(2, 5), sample(3, 9), { ...sample(4, 0), probe: "cache_bust", timing: { connect_ms: null, tls_ms: null, ttfb_ms: 450.7, total_ms: 460, rtt_ms: null } }] });
  expect(step("Request the page 3×").textContent).toContain("status 200, Age 0 → 9");
  expect(step("Force a miss").textContent).toContain("Age 0, 450.7 ms to first byte");
  emit({ stage: "traceroute", status: "completed", data: { hops: [{ n: 1, ip: "10.0.0.1" }, { n: 2, ip: "2.2.2.2" }] } });
  expect(step("Trace the route").textContent).toContain("2 hops, last 2.2.2.2");
  emit({ stage: "analyze", status: "started" });
  expect(step("Read the evidence").textContent).toContain("claude-opus-4-8 is reading 4 responses");
  expect(screen.getByText("https://www.persil.de/")).toBeInTheDocument();
});

test("a failed traceroute is an amber step with its reason, and the run continues", () => {
  renderRun(1);
  emit({ stage: "traceroute", status: "failed", data: { error: { message: "needs raw-socket permission" }, hops: [] } });
  expect(step("Trace the route")).toHaveClass("is-failed");
  expect(step("Trace the route").textContent).toContain("needs raw-socket permission");
  emit({ stage: "analyze", status: "completed", data: {} });
  emit({ stage: "pipeline", status: "done", terminal: true });
  expect(navigateMock).toHaveBeenCalledWith("/reports/rep-1", { replace: true });
});

test("raw headers disclosure shows request 1 as it lands", async () => {
  const user = userEvent.setup();
  renderRun(2);
  expect(screen.queryByText("Show raw headers")).toBeNull();
  emit({ stage: "sample", status: "completed", data: [sample(1, 0), sample(2, 0)] });
  const details = screen.getByText("Show raw headers").closest("details") as HTMLDetailsElement;
  await user.click(screen.getByText("Show raw headers"));
  expect(details.open).toBe(true);
  expect(within(details).getByText("x-cache")).toBeInTheDocument();
});

test("a terminal degraded event routes to the report view", () => {
  renderRun(1);
  emit({ stage: "analyze", status: "degraded", data: { status: "unavailable" } });
  emit({ stage: "pipeline", status: "done", terminal: true, degraded: true });
  expect(navigateMock).toHaveBeenCalledWith("/reports/rep-1", { replace: true });
});

test("a dropped stream shows a reconnect note that clears on replayed events", () => {
  renderRun(2);
  emit({ stage: "dns", status: "completed", data: {} });
  act(() => handlers.onError?.(new Error("drop")));
  expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
  emit({ stage: "pipeline", status: "running" });
  emit({ stage: "dns", status: "completed", data: {} });
  expect(screen.queryByText(/reconnecting/i)).not.toBeInTheDocument();
  expect(step("Look up DNS")).toHaveClass("is-done");
  expect(navigateMock).not.toHaveBeenCalled();
});

test("the subscription is opened once and closed on unmount", () => {
  const { unmount } = renderRun(1);
  expect(vi.mocked(subscribeAnalysis)).toHaveBeenCalledOnce();
  unmount();
  expect(closeMock).toHaveBeenCalled();
});

test("cancel stops the run and opens the report", async () => {
  const user = userEvent.setup();
  renderRun(2);
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(cancelAnalysis).toHaveBeenCalledWith("rep-1");
  await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/reports/rep-1", { replace: true }));
});

test("singular counts read naturally", () => {
  renderRun(1);
  emit({ stage: "dns", status: "completed", data: { a: ["1.1.1.1"], aaaa: [], cname_chain: [] } });
  expect(step("Look up DNS").textContent).toContain("1.1.1.1, 1 address");
  expect(step("Look up DNS").textContent).not.toContain("addresses");
  emit({ stage: "traceroute", status: "completed", data: { hops: [{ n: 1, ip: "10.0.0.1" }] } });
  expect(step("Trace the route").textContent).toContain("1 hop, last 10.0.0.1");
});

test("a header absent on every request reads 'no Age header', never 'Age — → —'", () => {
  renderRun(2);
  const bare = (request: number, extra: Record<string, unknown> = {}) => ({ ...sample(request, 0), headers: [["x-cache", "HIT"]], ...extra });
  emit({ stage: "sample", status: "completed", data: [bare(1), bare(2), bare(3, { probe: "cache_bust", timing: { connect_ms: null, tls_ms: null, ttfb_ms: 274.3, total_ms: 280, rtt_ms: null } })] });
  expect(step("Request the page 2×").textContent).toContain("status 200, no Age header");
  expect(step("Request the page 2×").textContent).not.toContain("—");
  expect(step("Force a miss").textContent).toContain("status 200, 274.3 ms to first byte");
  expect(step("Force a miss").textContent).not.toContain("Age");
});
