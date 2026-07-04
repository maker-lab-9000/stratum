import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

import type { StreamEvent, StreamHandlers } from "../api/client";
import { subscribeAnalysis } from "../api/client";
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
}));
vi.mock("react-router-dom", async (orig) => {
  const actual = (await orig()) as object;
  return { ...actual, useNavigate: () => navigateMock };
});

beforeEach(() => {
  navigateMock.mockReset();
  closeMock.mockReset();
  vi.mocked(subscribeAnalysis).mockClear();
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
function step(label: string) {
  return screen.getByText(label).closest(".stp") as HTMLElement;
}

// --- Scenario 1: events advance the stepper; N request steps from options ----

test("events advance the stepper in order; N request steps come from options", () => {
  renderRun(3);
  // The three request steps exist up front, before any sample lands.
  expect(step("Request 1")).toBeInTheDocument();
  expect(step("Request 2")).toBeInTheDocument();
  expect(step("Request 3")).toBeInTheDocument();
  expect(screen.queryByText("Request 4")).not.toBeInTheDocument();

  emit({ stage: "pipeline", status: "running" });
  emit({ stage: "dns", status: "started" });
  expect(step("Resolve DNS")).toHaveClass("is-active");
  emit({ stage: "dns", status: "completed", data: { a: [] } });
  expect(step("Resolve DNS")).toHaveClass("is-done");

  emit({ stage: "warm", status: "completed", data: {} });
  emit({ stage: "sample", status: "started" });
  expect(step("Request 2")).toHaveClass("is-active");
  emit({ stage: "traceroute", status: "started" });
  expect(step("Traceroute")).toHaveClass("is-active");
  emit({ stage: "analyze", status: "started" });
  expect(step("Analyze")).toHaveClass("is-active");
});

// --- Scenario 2: sampled headers render before any LLM event -----------------

test("raw headers appear when the sample lands, before the analyze step runs", () => {
  renderRun(2);
  expect(screen.queryByTestId("live-headers")).not.toBeInTheDocument();

  emit({
    stage: "sample",
    status: "completed",
    data: [
      { request: 1, http_version: "HTTP/2", status: 200, headers: [["x-cache", "MISS"]] },
      { request: 2, http_version: "HTTP/2", status: 200, headers: [["x-cache", "MISS"]] },
    ],
  });

  const panel = screen.getByTestId("live-headers");
  expect(within(panel).getByText("x-cache")).toBeInTheDocument();
  // The analyze step has not started, so headers are shown pre-LLM.
  expect(step("Analyze")).toHaveClass("is-pending");
  expect(navigateMock).not.toHaveBeenCalled();
});

// --- Scenario 3: a failed traceroute stage does not stop the run -------------

test("traceroute-failed shows a failed step yet the run proceeds to analyze + report", () => {
  renderRun(1);
  emit({ stage: "traceroute", status: "failed", data: { error: "no binary", hops: [] } });
  expect(step("Traceroute")).toHaveClass("is-failed");

  emit({ stage: "analyze", status: "started" });
  emit({ stage: "analyze", status: "completed", data: {} });
  expect(step("Analyze")).toHaveClass("is-done");
  emit({ stage: "pipeline", status: "done", terminal: true });
  expect(navigateMock).toHaveBeenCalledWith("/reports/rep-1", { replace: true });
});

// --- Scenario 4: terminal degraded event routes to the report ----------------

test("a terminal degraded event routes to the report view", () => {
  renderRun(1);
  emit({ stage: "analyze", status: "degraded", data: { status: "unavailable" } });
  emit({ stage: "pipeline", status: "done", terminal: true, degraded: true });
  expect(navigateMock).toHaveBeenCalledWith("/reports/rep-1", { replace: true });
});

// --- Scenario 5: a dropped stream reconnects without getting stuck -----------

test("a dropped stream shows a reconnect note that clears on replayed events", () => {
  renderRun(2);
  emit({ stage: "dns", status: "completed", data: {} });

  // Stream drops.
  act(() => handlers.onError?.(new Error("drop")));
  expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();

  // Reconnect replays buffered history (idempotent); the note clears and the
  // earlier progress is intact — no stuck spinner.
  emit({ stage: "pipeline", status: "running" });
  emit({ stage: "dns", status: "completed", data: {} });
  expect(screen.queryByText(/reconnecting/i)).not.toBeInTheDocument();
  expect(step("Resolve DNS")).toHaveClass("is-done");
  expect(navigateMock).not.toHaveBeenCalled();
});

test("the subscription is opened once and closed on unmount", () => {
  const { unmount } = renderRun(1);
  expect(vi.mocked(subscribeAnalysis)).toHaveBeenCalledOnce();
  unmount();
  expect(closeMock).toHaveBeenCalled();
});
