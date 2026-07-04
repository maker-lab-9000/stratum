import { afterEach, expect, test, vi } from "vitest";

import { subscribeAnalysis, type StreamEvent } from "./client";

// Build a mock Response whose body is a ReadableStream of SSE frames, then
// closes — the shape fetch() yields for text/event-stream.
function sseResponse(events: StreamEvent[], ok = true): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder();
      for (const e of events) controller.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`));
      controller.close();
    },
  });
  return { ok, body } as unknown as Response;
}

function waitFor(predicate: () => boolean, timeout = 1000): Promise<void> {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (predicate()) return resolve();
      if (Date.now() - started > timeout) return reject(new Error("waitFor timed out"));
      setTimeout(tick, 5);
    };
    tick();
  });
}

afterEach(() => vi.restoreAllMocks());

test("parses SSE frames into events and stops on the terminal event", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    sseResponse([
      { stage: "pipeline", status: "running" },
      { stage: "dns", status: "completed" },
      { stage: "pipeline", status: "done", terminal: true },
    ]),
  );
  vi.stubGlobal("fetch", fetchMock);

  const events: StreamEvent[] = [];
  subscribeAnalysis("rep-1", { onEvent: (e) => events.push(e) }, { reconnectDelayMs: 0 });

  await waitFor(() => events.some((e) => e.terminal));
  expect(events.map((e) => e.stage)).toEqual(["pipeline", "dns", "pipeline"]);
  // Terminal reached -> no reconnect.
  expect(fetchMock).toHaveBeenCalledOnce();
});

test("reconnects after a drop before terminal; backend replay recovers state", async () => {
  const onError = vi.fn();
  const fetchMock = vi
    .fn()
    // First connection drops mid-run (closes without a terminal event).
    .mockResolvedValueOnce(sseResponse([{ stage: "pipeline", status: "running" }, { stage: "dns", status: "completed" }]))
    // Reconnect: backend replays history, then the run terminates.
    .mockResolvedValueOnce(
      sseResponse([
        { stage: "pipeline", status: "running" },
        { stage: "dns", status: "completed" },
        { stage: "pipeline", status: "done", terminal: true },
      ]),
    );
  vi.stubGlobal("fetch", fetchMock);

  const events: StreamEvent[] = [];
  subscribeAnalysis("rep-1", { onEvent: (e) => events.push(e), onError }, { reconnectDelayMs: 0 });

  await waitFor(() => events.filter((e) => e.terminal).length === 1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(onError).toHaveBeenCalledOnce(); // the drop was signalled exactly once
});

test("closing stops reconnection", async () => {
  const fetchMock = vi.fn().mockResolvedValue(sseResponse([{ stage: "dns", status: "completed" }]));
  vi.stubGlobal("fetch", fetchMock);

  const close = subscribeAnalysis("rep-1", { onEvent: () => {} }, { reconnectDelayMs: 5 });
  close();
  // Give any in-flight reconnect a chance; it must not fire after close().
  await new Promise((r) => setTimeout(r, 40));
  expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(1);
});
