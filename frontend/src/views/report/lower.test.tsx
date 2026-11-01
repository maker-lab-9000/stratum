
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import type { Report } from "../../api/client";
import { akamaiReport } from "../../fixtures/akamaiReport";
import { Findings } from "./Findings";
import { Progression } from "./Progression";
import { RawDrawer } from "./RawDrawer";
import { MemoryRouter } from "react-router-dom";

import { ReportView } from "./ReportView";
import type { CacheVerdict, Finding, Layer } from "./types";

// --- builders ---------------------------------------------------------------

function layer(over: Partial<Layer>): Layer {
  return {
    layer_name: "L",
    vendor: "v",
    cache_type: "cache",
    role: "reverse_proxy",
    caches: true,
    state: "PASS",
    evidence_headers: ["x-cache: MISS"],
    ...over,
  };
}

function verdict(layers: Layer[], servingName: string, over: Partial<CacheVerdict> = {}): CacheVerdict {
  return {
    cached: true,
    confidence: "high",
    provider: "Test",
    provider_evidence: [],
    serving_layer: servingName,
    layer_count_to_origin: layers.filter((l) => l.caches).length,
    layers,
    sample_states: [],
    ...over,
  };
}

// --- Scenario 1: any layer count renders; flag never collides ---------------

// --- Scenario 2: UNKNOWN node is dashed, distinct from dimmed not-reached ----

// --- Scenario 3: N<=6 renders columns; N>6 renders a hover strip ------------

function samples(n: number, headers: [string, string][] = [["age", "0"], ["cache-control", "no-store"]]) {
  return Array.from({ length: n }, (_, i) => ({
    request: i + 1,
    http_version: "HTTP/2",
    status: 200,
    started_at_ms: i * 2000,
    headers,
  }));
}

test("progression uses request columns at N=4 and a hover strip at N=10", () => {
  const layers = [layer({ layer_name: "Proxy", state: "HIT" })];
  const states4 = [1, 2, 3, 4].map((r) => ({ request: r, state: "MISS", evidence_headers: [] }));
  const v4 = verdict(layers, "Proxy", { sample_states: states4 });
  const { container, rerender } = render(<Progression verdict={v4} samples={samples(4)} />);

  // Four request columns, no strip.
  expect(screen.getByText("Request 1")).toBeInTheDocument();
  expect(screen.getByText("cold")).toBeInTheDocument();
  expect(container.querySelectorAll("thead th")).toHaveLength(5); // Signal + 4
  expect(container.querySelector(".strip")).toBeNull();

  // N=10 collapses the state row to a strip with per-request hover titles.
  const states10 = Array.from({ length: 10 }, (_, i) => ({
    request: i + 1,
    state: i === 0 ? "MISS" : "HIT",
    evidence_headers: [],
  }));
  const v10 = verdict(layers, "Proxy", { sample_states: states10 });
  rerender(<Progression verdict={v10} samples={samples(10)} />);
  const strip = container.querySelector(".strip");
  expect(strip).not.toBeNull();
  expect(strip!.querySelectorAll("i")).toHaveLength(10);
  expect(within(strip as HTMLElement).getByTitle("Request 1: MISS")).toBeInTheDocument();
  expect(within(strip as HTMLElement).getByTitle("Request 10: HIT")).toBeInTheDocument();
});

// --- Scenario 4: findings collapse past 3, severity-sorted ------------------

test("findings are one severity-sorted list with meters", async () => {
  const user = userEvent.setup();
  const security: Finding[] = [
    { severity: "info", title: "S-info", description: "d", evidence_header: "server: x", confidence: "medium" },
    { severity: "warning", title: "S-warn", description: "d", evidence_header: "Strict-Transport-Security" },
  ];
  const performance: Finding[] = [
    { severity: "critical", title: "P-crit", description: "d", evidence_header: "Age: 0", confidence: "high" },
    { severity: "warning", title: "P-warn", description: "d", evidence_header: "Age: 0" },
    { severity: "info", title: "P-info1", description: "d", evidence_header: "Age: 0" },
    { severity: "info", title: "P-info2", description: "d", evidence_header: "Age: 0" },
  ];
  const gap = { status: "gap" as const, summary: "S", hidden_layer_suspected: true, confidence: "medium", evidence: ["request 2 server_ms: 3.2"] };
  const { container } = render(<Findings security={security} performance={performance} timing={gap} />);
  const titles = () => Array.from(container.querySelectorAll(".finding-title")).map((t) => t.textContent);
  expect(titles()).toEqual(["P-crit", "Timing doesn't match the headers", "S-warn", "P-warn", "S-info"]);
  const row = (title: string) => (container.querySelector(`[data-title="${title}"]`) as HTMLElement);
  expect(row("S-warn").textContent).toContain("Security");
  expect(row("P-crit").textContent).toContain("Performance");
  expect(within(row("P-crit")).getByRole("img", { name: "Confidence: high" })).toBeInTheDocument();
  expect(within(row("P-warn")).getByRole("img", { name: "Not rated" })).toBeInTheDocument();
  expect(within(row("Timing doesn't match the headers")).getByRole("img", { name: "Confidence: medium" })).toBeInTheDocument();
  expect(within(row("P-crit")).getByText("Age: 0").tagName).toBe("CODE");
  await user.click(screen.getByRole("button", { name: "Show all (7)" }));
  expect(titles()).toHaveLength(7);
});


// --- Scenario 5: chain flips to a vertical timeline below ~700px -------------

// --- Scenario 6: header/evidence values are inert text (XSS) -----------------

test("an injection probe in a header value renders as text, never as markup", () => {
  const probe = '<img src=x onerror="alert(1)">';
  const xssReport: Report = {
    ...akamaiReport,
    samples_json: [
      { request: 1, http_version: "HTTP/2", status: 200, headers: [["x-evil", probe]] },
    ] as unknown as Report["samples_json"],
    verdict_json: {
      ...(akamaiReport.verdict_json as object),
      layers: [layer({ layer_name: "Proxy", state: "HIT", evidence_headers: [`x-evil: ${probe}`] })],
      serving_layer: "Proxy",
      validation: { ok: true, flags: [] },
    } as unknown as Report["verdict_json"],
  };

  const { container } = render(<MemoryRouter><ReportView report={xssReport} /></MemoryRouter>);

  // No live <img> was ever created from the payload.
  expect(container.querySelector("img")).toBeNull();
  // The literal probe text is present (escaped) in both the raw drawer and the
  // topology node evidence.
  expect(screen.getAllByText((_, el) => el?.textContent?.includes(probe) ?? false).length).toBeGreaterThan(0);
});

// --- Scenario 6 (extended): script tags, ANSI, and a 10KB value stay inert ---

test("malicious header values (script/ANSI/10KB) render as text, UI intact", () => {
  const script = "<script>window.__pwned=1</script>";
  const ansi = "[31mRED[0m payload";
  const huge = "B".repeat(10_240);
  const malicious: Report = {
    ...akamaiReport,
    samples_json: [
      {
        request: 1,
        http_version: "HTTP/2",
        status: 200,
        headers: [
          ["x-xss", script],
          ["x-ansi", ansi],
          ["x-huge", huge],
        ],
      },
    ] as unknown as Report["samples_json"],
    verdict_json: {
      ...(akamaiReport.verdict_json as object),
      layers: [layer({ layer_name: "Proxy", state: "HIT", evidence_headers: [`x-xss: ${script}`] })],
      serving_layer: "Proxy",
      validation: { ok: true, flags: [] },
    } as unknown as Report["verdict_json"],
  };

  const { container } = render(<MemoryRouter><ReportView report={malicious} /></MemoryRouter>);

  // No live nodes were ever created from the payload, and nothing executed.
  expect(container.querySelector("script")).toBeNull();
  expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  // The raw drawer shows the values as inert text (React-escaped).
  const raw = screen.getByTestId("raw-body");
  expect(raw.textContent).toContain(script);
  expect(raw.textContent).toContain(ansi);
  // The 10KB value renders in full without breaking the layout (text node present).
  expect(raw.textContent).toContain(huge);
});

test("RawDrawer switches to a <select> beyond 8 requests", () => {
  render(<RawDrawer samples={samples(10)} />);
  expect(screen.getByLabelText("Select request")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Request 1/ })).not.toBeInTheDocument();
});

// --- 1.2.0: timing rows, cache-bust probe ----------------------------------

function timed(
  request: number,
  ttfb: number | null,
  extra: { connect?: number; probe?: boolean; headers?: [string, string][] } = {},
) {
  return {
    request,
    http_version: "HTTP/2",
    status: 200,
    started_at_ms: (request - 1) * 1500,
    headers: extra.headers ?? ([["age", "0"]] as [string, string][]),
    peer_ip: "18.64.119.98",
    timing: { connect_ms: null, tls_ms: null, ttfb_ms: ttfb, total_ms: ttfb, rtt_ms: extra.connect ?? null },
    ...(extra.probe ? { probe: "cache_bust" } : {}),
  };
}

const TIMED = [
  timed(1, 79.5, { connect: 38.2 }),
  timed(2, 41.4),
  timed(3, 42.0),
  timed(4, 450.7, { probe: true }),
];

function rowCells(container: HTMLElement, label: string): string[] {
  const th = Array.from(container.querySelectorAll("tbody th")).find((el) => el.textContent === label);
  if (!th) return [];
  return Array.from(th.parentElement!.querySelectorAll("td")).map((td) => td.textContent ?? "");
}

test("timing rows render from samples", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const { container, rerender } = render(<Progression verdict={v} samples={TIMED} />);
  expect(rowCells(container, "TTFB")).toEqual(["79.5 ms", "41.4 ms", "42 ms", "450.7 ms"]);
  expect(rowCells(container, "Server time")).toEqual(["41.3 ms", "3.2 ms", "3.8 ms", "412.5 ms"]);
  expect(screen.getByText("cache-bust")).toBeInTheDocument();

  rerender(<Progression verdict={v} samples={samples(3)} />);
  expect(rowCells(container, "TTFB")).toEqual([]);
  expect(rowCells(container, "Server time")).toEqual([]);
});

test("probe note when N > 6", () => {
  const many = [timed(1, 79.5, { connect: 38.2 }), ...Array.from({ length: 7 }, (_, i) => timed(i + 2, 41))];
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  render(<Progression verdict={v} samples={[...many, timed(9, 450.7, { probe: true })]} />);
  expect(screen.queryByText("cache-bust")).toBeNull();
  const note = screen.getByText(/cache-bust probe/i);
  expect(note.textContent).toContain("412.5 ms");
});

test("raw drawer probe tab", async () => {
  const user = userEvent.setup();
  const withProbe = [...TIMED.slice(0, 3), timed(4, 450.7, { probe: true, headers: [["x-probe-only", "abc"]] })];
  render(<RawDrawer samples={withProbe} />);
  await user.click(screen.getByRole("button", { name: "Cache-bust probe" }));
  expect(screen.getByTestId("raw-body").textContent).toContain("x-probe-only");
});

// --- 1.3.1: real-data progression rows ------------------------------------------

test("server time under 1 ms reads <1 ms, exact value on hover", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const s = [timed(1, 79.5, { connect: 38.2 }), timed(2, 36.9), timed(3, 38.7)];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "Server time")).toEqual(["41.3 ms", "<1 ms", "<1 ms"]);
  const th = Array.from(container.querySelectorAll("tbody th")).find((el) => el.textContent === "Server time")!;
  const cells = Array.from(th.parentElement!.querySelectorAll("td"));
  expect(cells[1]).toHaveAttribute("title", "-1.3 ms measured");
  expect(cells[2]).toHaveAttribute("title", "0.5 ms measured");
});

test("headers absent on every request fold into one 'Not sent' line", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const s = samples(3, [["cache-control", "max-age=300"]]);
  const { container, rerender } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "Age")).toEqual([]);
  expect(rowCells(container, "Via")).toEqual([]);
  expect(rowCells(container, "Cache-Control")).toEqual(["max-age=300"]);
  expect(screen.getByText("Not sent: Age, Via.")).toBeInTheDocument();

  // Present on the probe only → the row stays.
  const probe = { ...timed(4, 300, { probe: true, headers: [["age", "0"]] }) };
  rerender(<Progression verdict={v} samples={[...s, probe]} />);
  expect(rowCells(container, "Age")).toEqual(["—", "0"]);
  expect(screen.getByText("Not sent: Via.")).toBeInTheDocument();
});

const vary = (request: number, extra: [string, string][], probe = false) => ({
  ...timed(request, null, { probe, headers: [["date", `Sat, 01 Nov 2026 10:00:0${request} GMT`], ["server", "nginx"], ...extra] }),
});

test("headers whose value changes between requests get their own rows", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const s = [
    vary(1, [["x-cache", "MISS"], ["x-served-by", "cache-fra-1"], ["x-request-id", "a1"]]),
    vary(2, [["x-cache", "HIT"], ["x-served-by", "cache-fra-2"], ["x-request-id", "b2"]]),
    vary(3, [["x-cache", "HIT"], ["x-served-by", "cache-fra-1"], ["x-request-id", "c3"]]),
    vary(4, [["X-Cache", "MISS"], ["x-served-by", "cache-fra-2"], ["x-request-id", "d4"]], true),
  ];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "x-cache")).toEqual(["MISS", "HIT", "HIT", "MISS"]);
  expect(rowCells(container, "x-served-by")).toEqual(["cache-fra-1", "cache-fra-2", "cache-fra-1", "cache-fra-2"]);
  expect(rowCells(container, "x-request-id")).toEqual(["a1", "b2", "c3", "d4"]);
  // Constant headers and the clock never get a row.
  expect(rowCells(container, "server")).toEqual([]);
  expect(rowCells(container, "date")).toEqual([]);
  // Fewest distinct values first: flips before per-request IDs.
  const labels = Array.from(container.querySelectorAll("tbody th")).map((th) => th.textContent);
  expect(labels.indexOf("x-cache")).toBeLessThan(labels.indexOf("x-request-id"));
  expect(labels.indexOf("x-served-by")).toBeLessThan(labels.indexOf("x-request-id"));
});

test("a header that only differs on the cache-bust probe gets a row", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const s = [
    vary(1, [["x-cache", "HIT"]]),
    vary(2, [["x-cache", "HIT"]]),
    vary(3, [["x-cache", "BYPASS"], ["set-cookie", "wordpress_test_cookie=WP"]], true),
  ];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "x-cache")).toEqual(["HIT", "BYPASS"]);
  expect(rowCells(container, "set-cookie")).toEqual(["—", "wordpress_test_cookie=WP"]);
});

test("changing-header rows cap at six; the rest are named in a note", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const names = ["x-a", "x-b", "x-c", "x-d", "x-e", "x-f", "x-g", "x-h"];
  const s = [1, 2].map((r) => vary(r, names.map((n) => [n, `${n}-${r}`] as [string, string])));
  const { container } = render(<Progression verdict={v} samples={s} />);
  for (const n of names.slice(0, 6)) expect(rowCells(container, n)).toHaveLength(2);
  expect(rowCells(container, "x-g")).toEqual([]);
  expect(screen.getByText("Also changed between requests: x-g, x-h.")).toBeInTheDocument();
});

// --- 1.3.2: matching probe spans; random per-request ids fold into a note ------

test("a value the cache-bust shares with every request spans its column too", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const cc: [string, string] = ["cache-control", "max-age=60, private"];
  const s = [vary(1, [cc]), vary(2, [cc]), vary(3, [cc]), vary(4, [cc], true)];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "Cache-Control")).toEqual(["max-age=60, private"]);
  const th = Array.from(container.querySelectorAll("tbody th")).find((el) => el.textContent === "Cache-Control")!;
  expect(th.parentElement!.querySelector("td")).toHaveAttribute("colspan", "4");
});

test("random per-request ids fold into one line; other changing values keep their rows", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const ids = ["efd30094-759c-40f6-8cdc-49335e88b31b", "62d75268-e4e3-4eb2-bcad-476a3daae087", "f60f5f1d-5e3d-48b9-802e-691549d6688a"];
  const s = [1, 2, 3].map((r) =>
    vary(r, [["x-request-id", ids[r - 1]], ["x-timer", `S179355156${r}.6,VS0,VE${r}`], ["x-served-by", `cache-fra-etou822016${r}-FRA`]], r === 3),
  );
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "x-request-id")).toEqual([]);
  expect(rowCells(container, "x-timer")).toHaveLength(3);
  expect(rowCells(container, "x-served-by")).toHaveLength(3);
  expect(screen.getByText("Unique per request: x-request-id.")).toBeInTheDocument();
});

test("an id row stays when one column lacks it or two columns share a value", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "HIT" })], "Proxy");
  const s = [vary(1, [["x-trace", "0123456789abcdef01"]]), vary(2, [["x-trace", "fedcba9876543210ff"]]), vary(3, [])];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "x-trace")).toEqual(["0123456789abcdef01", "fedcba9876543210ff", "—"]);
  expect(screen.queryByText(/Unique per request/)).toBeNull();
});

test("a very long changing-header value is clamped, with the full value on hover", () => {
  const v = verdict([layer({ layer_name: "Proxy", state: "MISS" })], "Proxy");
  const cookie = `_abck=${"4E163B7FF129ADF23E19699ECB3B2B78~-1~YAAQ".repeat(20)}; Path=/; Secure`;
  const s = [vary(1, [["set-cookie", cookie]]), vary(2, []), vary(3, [])];
  const { container } = render(<Progression verdict={v} samples={s} />);
  expect(rowCells(container, "set-cookie")).toEqual([cookie, "—", "—"]);
  const clamped = container.querySelector("table.prog td .clamp");
  expect(clamped).not.toBeNull();
  expect(clamped).toHaveAttribute("title", cookie);
  // Short values stay plain text.
  const short = vary(1, [["x-cache", "HIT"]]);
  const { container: c2 } = render(<Progression verdict={v} samples={[short, vary(2, [["x-cache", "MISS"]])]} />);
  expect(c2.querySelector("table.prog td .clamp")).toBeNull();
});
