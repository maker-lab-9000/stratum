import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";

import type { Report } from "../../api/client";
import { akamaiReport } from "../../fixtures/akamaiReport";
import { DnsPanel } from "./DnsPanel";
import { ReportView } from "./ReportView";
import { VerdictTiles } from "./VerdictTiles";
import type { CacheVerdict, Dns } from "./types";

function renderReport(report: Report) {
  return render(
    <MemoryRouter>
      <ReportView report={report} />
    </MemoryRouter>,
  );
}

// --- Scenario 1: akamai_bypass fixture renders Section-01 content -------------

test("akamai_bypass report renders verdict + all Section-01 content", () => {
  const { container } = renderReport(akamaiReport);

  // Verdict tiles, user->origin order (scoped: "Apache Dispatcher"/"Akamai" also
  // appear once Section 02's chain + layer table render).
  const tiles = container.querySelector(".verdict") as HTMLElement;
  expect(within(tiles).getByText("Bypassed")).toBeInTheDocument();
  expect(within(tiles).getByText("Apache Dispatcher")).toBeInTheDocument();
  expect(within(tiles).getByText("Akamai")).toBeInTheDocument();

  // DNS panel: CDN detected + data-driven signature label.
  expect(screen.getByText("CDN detected")).toBeInTheDocument();
  expect(screen.getByText("example-foods.com.edgekey.net")).toBeInTheDocument();
  expect(screen.getAllByText("Akamai signature").length).toBeGreaterThan(0);

  // Geomap (Berlin -> Frankfurt both resolvable) rather than the strip fallback.
  expect(screen.getByTestId("geomap")).toBeInTheDocument();

  // Hop ladder (a middle hop + the edge anchor); scoped to the hops table since
  // "Akamai Edge" is also a Section 02 layer name.
  const hops = container.querySelector("table.hops") as HTMLElement;
  expect(within(hops).getByText("62.155.241.18")).toBeInTheDocument();
  expect(within(hops).getByText(/Akamai Edge/)).toBeInTheDocument();

  // Segment narration + measurement seam (edge IP appears in DNS, hop, and seam).
  expect(screen.getByText("Access")).toBeInTheDocument();
  const seam = screen.getByText("▲ traceroute ends").closest(".route-seam")!;
  expect(within(seam as HTMLElement).getByText("23.55.142.16")).toBeInTheDocument();
});

// --- Scenario 2: UNKNOWN verdict + failed citation ---------------------------

test("UNKNOWN CDN state + failed citation -> unknown tile + unverified tag", () => {
  const verdict = akamaiReport.verdict_json as unknown as CacheVerdict;
  const unknownReport: Report = {
    ...akamaiReport,
    verdict_json: {
      ...verdict,
      layers: verdict.layers.map((l, i) => (i === 0 ? { ...l, state: "UNKNOWN" } : l)),
      validation: {
        ok: false,
        flags: [
          { path: "cache_verdict.layers[0].state", citation: "x-cache: TCP_HIT", reason: "not found" },
        ],
      },
    } as unknown as Record<string, unknown>,
  };

  render(<VerdictTiles report={unknownReport} />);
  const cdnTile = screen.getByText("CDN cache").closest(".tile")!;
  expect(within(cdnTile as HTMLElement).getByText("Unknown")).toBeInTheDocument();
  expect(cdnTile).toHaveClass("is-unknown");
  expect(within(cdnTile as HTMLElement).getByText("unverified")).toBeInTheDocument();
});

// --- Scenario 3: degraded report ---------------------------------------------

test("degraded report -> banner + '—' tiles + evidence still renders", () => {
  const degraded: Report = {
    ...akamaiReport,
    verdict_json: { status: "unavailable", reason: "LLM returned invalid output after 2 attempts" },
    llm_json: null,
  };
  renderReport(degraded);

  expect(screen.getByText("Verdict unavailable.")).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4); // all four tiles
  // Measured evidence still renders.
  expect(screen.getByText("62.155.241.18")).toBeInTheDocument(); // a hop
  expect(screen.getByText("example-foods.com.edgekey.net")).toBeInTheDocument(); // dns
});

// --- Scenario 6: long CNAME -> siglabel on its own line ----------------------

test("long CNAME -> signature label is a separate block element", () => {
  const longHost = "example-foods-content-delivery-network.global.prod.fastly.edgekey.net"; // 60+ chars
  const dns: Dns = {
    a: ["1.2.3.4"],
    aaaa: [],
    cname_chain: [{ name: "www.x.com", cname: longHost, ttl: 20 }],
    ns: ["ns1.x"],
    ttl: 20,
  };
  const verdict = {
    provider: "Akamai",
    provider_evidence: [longHost],
  } as unknown as CacheVerdict;

  const { container } = render(<DnsPanel dns={dns} verdict={verdict} />);
  expect(screen.getByText(longHost)).toBeInTheDocument();
  const siglabel = container.querySelector(".siglabel");
  expect(siglabel).not.toBeNull();
  expect(siglabel).toHaveTextContent("Akamai signature");
  // Rendered as real DOM (its own <span>), never CSS content overlaid on the host.
  expect(siglabel!.tagName).toBe("SPAN");
});

// --- 1.2.0: probe excluded from counts; seam text per status ------------------

import { MeasurementSeam } from "./MeasurementSeam";
import type { Hop, Seam } from "./types";

function timedSample(request: number, probe = false) {
  return {
    request,
    ok: true,
    http_version: "HTTP/2",
    status: 200,
    started_at_ms: (request - 1) * 1500,
    headers: [["age", "0"]] as [string, string][],
    timing: { connect_ms: null, tls_ms: null, ttfb_ms: 40 + request, total_ms: 50, rtt_ms: request === 1 ? 38.2 : null },
    ...(probe ? { probe: "cache_bust" } : {}),
  };
}

test("probe excluded from request columns and counts", () => {
  const report = {
    ...akamaiReport,
    samples_json: [timedSample(1), timedSample(2), timedSample(3), timedSample(4, true)],
  } as unknown as Report;
  const { container } = renderReport(report);
  expect(screen.getByText("3 requests")).toBeInTheDocument();
  expect(screen.getByText(/3 consecutive requests/)).toBeInTheDocument();
  const prog = container.querySelector("table.prog, .prog table, table") as HTMLElement;
  const heads = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent ?? "");
  expect(heads.filter((h) => h.startsWith("Request"))).toHaveLength(3);
  expect(heads.some((h) => h.includes("cache-bust"))).toBe(true);
  const stateRow = Array.from(container.querySelectorAll("tbody th"))
    .find((el) => el.textContent === "Cache state")!.parentElement!;
  const cells = Array.from(stateRow.querySelectorAll("td"));
  expect(cells).toHaveLength(4);
  expect(cells.slice(0, 3).every((td) => td.querySelector(".tag"))).toBe(true);
  expect(cells[3].textContent).toBe("");
  expect(prog).not.toBeNull();
});

const SEAM_HOPS: Hop[] = [
  { n: 7, ip: "23.55.142.16", rdns: null, asn: 20940, org: "Akamai", city: "Frankfurt", rtt_ms: 15, private: false, unresponsive: false, hint: null },
];

test("seam text per status", () => {
  const seam = (status: Seam["status"]): Seam => ({ status, traced_ip: "23.55.142.16", peer_ips: ["23.55.142.99"] });
  const { container, rerender } = render(<MeasurementSeam hops={SEAM_HOPS} />);
  expect(container.textContent).toContain("the same node");

  rerender(<MeasurementSeam hops={SEAM_HOPS} seam={seam("confirmed")} />);
  expect(container.textContent).toContain("the same node");

  rerender(<MeasurementSeam hops={SEAM_HOPS} seam={seam("different_edge")} />);
  expect(container.textContent).toContain("another server for this hostname");
  expect(container.textContent).not.toContain("the same node");
  expect(container.textContent).toContain("23.55.142.99");

  rerender(<MeasurementSeam hops={SEAM_HOPS} seam={seam("unconfirmed")} />);
  expect(container.textContent).toContain("inferred, not measured");
});

// --- 1.2.0: headline confidence (layout C), timing gap tag, timing card -------

import { Findings } from "./Findings";
import type { Finding, TimingCheck } from "./types";

function withVerdict(over: Partial<CacheVerdict>): Report {
  return {
    ...akamaiReport,
    verdict_json: { ...(akamaiReport.verdict_json as object), ...over },
  } as unknown as Report;
}

const GAP: TimingCheck = {
  status: "gap",
  summary: "S",
  hidden_layer_suspected: true,
  confidence: "medium",
  evidence: ["request 2 server_ms: 3.2"],
};

function servedFromTile(container: HTMLElement): HTMLElement {
  const tiles = Array.from(container.querySelectorAll(".verdict .tile")) as HTMLElement[];
  return tiles.find((t) => t.textContent?.includes("Served from"))!;
}

test("confidence line shows level, bar and reason", () => {
  const { container } = renderReport(
    withVerdict({ confidence: "medium", confidence_reason: "lowered: timing disagrees with the headers" }),
  );
  const line = container.querySelector(".verdict-conf") as HTMLElement;
  expect(line).not.toBeNull();
  expect(within(line).getByText("Verdict confidence")).toBeInTheDocument();
  expect(within(line).getByText("Medium")).toBeInTheDocument();
  expect(within(line).getByText("lowered: timing disagrees with the headers")).toBeInTheDocument();
  expect(line.querySelectorAll(".conf-bar")).toHaveLength(1);
  expect(container.querySelector(".verdict .conf-bar")).toBeNull();
});

test("confidence line shows unverified badge for validator notes", () => {
  const { container } = renderReport(
    withVerdict({ confidence: "low", confidence_reason: "x · citation check: serving-layer evidence not found" }),
  );
  const line = container.querySelector(".verdict-conf") as HTMLElement;
  expect(line.querySelector(".unverified")).not.toBeNull();
});

test("confidence line hidden when degraded", () => {
  renderReport({ ...akamaiReport, verdict_json: { status: "unavailable", reason: "x" } } as unknown as Report);
  expect(screen.queryByText("Verdict confidence")).toBeNull();
});

test("timing gap tag on served-from tile", () => {
  const gap = renderReport(withVerdict({ timing_check: GAP }));
  expect(servedFromTile(gap.container).textContent).toContain("timing gap");
  gap.unmount();
  const ok = renderReport(withVerdict({ timing_check: { ...GAP, status: "consistent" } }));
  expect(servedFromTile(ok.container).textContent).not.toContain("timing gap");
});

const PERF: Finding[] = [
  { severity: "warning", title: "Other warning", description: "w", evidence_header: "Age" },
  { severity: "critical", title: "Critical one", description: "c", evidence_header: "Age" },
];

function perfTitles(container: HTMLElement): string[] {
  const col = Array.from(container.querySelectorAll(".find-col")).find((c) =>
    c.querySelector("h4")?.textContent?.startsWith("Performance"),
  )!;
  return Array.from(col.querySelectorAll(".ttl")).map((t) => t.textContent ?? "");
}

test("timing card first among warnings", () => {
  const { container } = render(<Findings security={[]} performance={PERF} timing={GAP} />);
  expect(perfTitles(container)).toEqual(["Critical one", "Timing doesn't match the headers", "Other warning"]);
  const card = Array.from(container.querySelectorAll(".card")).find((c) =>
    c.textContent?.includes("Timing doesn't match the headers"),
  ) as HTMLElement;
  expect(card.textContent).toContain("S");
  expect(card.textContent).toContain("LLM confidence · medium");
  expect(within(card).getByText("request 2 server_ms: 3.2").tagName).toBe("CODE");
});

test("insufficient summary renders as info card", () => {
  const insufficient: TimingCheck = { ...GAP, status: "insufficient", summary: "T", hidden_layer_suspected: false };
  const { container, rerender } = render(<Findings security={[]} performance={[]} timing={insufficient} />);
  const info = container.querySelector(".card.info") as HTMLElement;
  expect(info?.textContent).toContain("T");
  rerender(<Findings security={[]} performance={[]} timing={{ ...insufficient, summary: "" }} />);
  expect(container.querySelector(".card")).toBeNull();
});

test("old report renders without confidence reason or tag", () => {
  const { container } = renderReport(akamaiReport);
  const line = container.querySelector(".verdict-conf") as HTMLElement;
  expect(within(line).getByText("Verdict confidence")).toBeInTheDocument();
  expect(within(line).getByText("High")).toBeInTheDocument();
  expect(line.querySelector(".conf-reason")).toBeNull();
  expect(container.textContent).not.toContain("timing gap");
});
