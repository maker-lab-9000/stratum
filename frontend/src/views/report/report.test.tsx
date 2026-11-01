import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";

import type { Report } from "../../api/client";
import { akamaiReport, akamaiReportLegacy } from "../../fixtures/akamaiReport";
import { DnsPanel } from "./DnsPanel";
import { ReportView } from "./ReportView";
import type { CacheVerdict, Dns } from "./types";

function renderReport(report: Report) {
  return render(
    <MemoryRouter>
      <ReportView report={report} />
    </MemoryRouter>,
  );
}

// --- Scenario 1: akamai_bypass fixture renders Section-01 content -------------

// --- Scenario 2: UNKNOWN verdict + failed citation ---------------------------

// --- Scenario 3: degraded report ---------------------------------------------

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

import { Hosted } from "./Hosted";
import type { Seam } from "./types";

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
  expect(screen.getByText(/3 consecutive requests/)).toBeInTheDocument();
  const prog = container.querySelector("table.prog, .prog table, table") as HTMLElement;
  const heads = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent ?? "");
  expect(heads.filter((h) => h.startsWith("Request"))).toHaveLength(3);
  expect(heads.some((h) => h.includes("cache-bust"))).toBe(true);
  const stateRow = Array.from(container.querySelectorAll("tbody th"))
    .find((el) => el.textContent === "Model's reading")!.parentElement!;
  const cells = Array.from(stateRow.querySelectorAll("td"));
  expect(cells).toHaveLength(4);
  expect(cells.slice(0, 3).every((td) => td.querySelector(".tag"))).toBe(true);
  expect(cells[3].textContent).toBe("");
  expect(prog).not.toBeNull();
});


test("seam text per status", () => {
  const withSeam = (status?: Seam["status"]) =>
    ({
      ...akamaiReport,
      traceroute_json: {
        ...(akamaiReport.traceroute_json as object),
        ...(status ? { seam: { status, traced_ip: "23.55.142.16", peer_ips: ["23.55.142.99"] } } : {}),
      },
    }) as unknown as Report;
  const text = (r: Report) => {
    const { container, unmount } = render(<MemoryRouter><Hosted report={r} /></MemoryRouter>);
    const t = container.textContent ?? "";
    unmount();
    return t;
  };
  expect(text(withSeam())).toContain("the same node");
  expect(text(withSeam("confirmed"))).toContain("the same node");
  const different = text(withSeam("different_edge"));
  expect(different).toContain("another server for this hostname");
  expect(different).not.toContain("the same node");
  expect(different).toContain("23.55.142.99");
  expect(text(withSeam("unconfirmed"))).toContain("inferred, not measured");
});


// --- 1.2.0: headline confidence (layout C), timing gap tag, timing card -------

import { Findings } from "./Findings";
import type { TimingCheck } from "./types";

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




test("only a timing gap becomes a finding (1.3.1: no duplicate of the Timing claim row)", () => {
  const insufficient: TimingCheck = { ...GAP, status: "insufficient", summary: "T", hidden_layer_suspected: false };
  const { container, rerender } = render(<Findings security={[]} performance={[]} timing={insufficient} />);
  expect(container.querySelector(".finding")).toBeNull();
  rerender(<Findings security={[]} performance={[]} timing={{ ...insufficient, status: "consistent" }} />);
  expect(container.querySelector(".finding")).toBeNull();
  rerender(<Findings security={[]} performance={[]} timing={GAP} />);
  expect(container.querySelector(".finding.warn")?.textContent).toContain("Timing doesn't match the headers");
});



// --- 1.3.0: the answer, the strata, the claim rows ---------------------------

import type { Layer } from "./types";

const V0 = akamaiReport.verdict_json as unknown as CacheVerdict;

function withLayers(layers: Layer[], over: Partial<CacheVerdict> = {}): Report {
  return withVerdict({ layers, ...over });
}

test("answer shows headline, detail, big meter and reason", () => {
  const { container } = renderReport(withVerdict({ confidence_reason: "Age climbs while the edge misses." }));
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1.textContent).toContain(V0.headline!);
  expect(h1.textContent).toContain(V0.headline_detail!);
  expect(container.querySelectorAll(".meter-lg")).toHaveLength(1);
  const gauge = container.querySelector(".gauge") as HTMLElement;
  expect(within(gauge).getByRole("img", { name: "Confidence: high" })).toBeInTheDocument();
  expect(within(gauge).getByText("High confidence")).toBeInTheDocument();
  expect(screen.getByText("Age climbs while the edge misses.")).toBeInTheDocument();
  expect(container.querySelector(".gauge .unverified")).toBeNull();

  const noted = renderReport(withVerdict({ confidence_reason: "x · citation check: serving-layer evidence not found" }));
  expect(noted.container.querySelector(".gauge .unverified")).not.toBeNull();
});

test("answer degraded and failed states", () => {
  renderReport({ ...akamaiReport, verdict_json: { status: "unavailable", reason: "LLM returned invalid output after 2 attempts" }, llm_json: null } as unknown as Report);
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1.textContent).toContain("No verdict");
  expect(h1.textContent).toContain("The model couldn't read the evidence: LLM returned invalid output after 2 attempts.");
  expect(within(document.querySelector(".answer") as HTMLElement).getByRole("button", { name: "Re-run" })).toBeInTheDocument();
  expect(document.querySelector(".strata")).toBeNull();
});

test("answer for a failed run", () => {
  renderReport({ ...akamaiReport, status: "error", error: "no successful samples collected", verdict_json: null, llm_json: null } as unknown as Report);
  const h1 = screen.getByRole("heading", { level: 1 });
  expect(h1.textContent).toContain("Analysis failed");
  expect(h1.textContent).toContain("no successful samples collected");
});

test("strata bands follow the chain", () => {
  const flagged = withVerdict({
    validation: { ok: false, flags: [{ path: "cache_verdict.layers[0].state", citation: "x", reason: "r" }] },
  });
  const { container } = renderReport(flagged);
  const strata = container.querySelector(".strata") as HTMLElement;
  expect(strata.querySelector(".strata-surface")!.textContent).toBe("You, in Berlin, DE · Playwright runner");
  const bands = Array.from(strata.querySelectorAll(".band")) as HTMLElement[];
  expect(bands).toHaveLength(V0.layers.length);
  const served = bands[2];
  expect(served).toHaveClass("served");
  expect(served.textContent).toContain("Hit, served the page");
  expect(within(served).getByText("server-timing: dispatcher;desc=HIT").tagName).toBe("CODE");
  expect(within(served).getByRole("img", { name: `Confidence: ${V0.layers[2].confidence}` })).toBeInTheDocument();
  expect(bands[3]).toHaveClass("unreached");
  expect(bands[3].textContent).toContain("Not reached");
  expect(bands[0].querySelector(".unverified")).not.toBeNull();
});

test("strata note when origin not listed", () => {
  const noOrigin = V0.layers.slice(0, 3);
  const { container } = renderReport(withLayers(noOrigin));
  expect(container.querySelectorAll(".band")).toHaveLength(3);
  expect(screen.getByText("The model didn't list the origin layer.")).toBeInTheDocument();
});

test("origin-serve band is blue, not green", () => {
  const origin: Layer = { ...V0.layers[3], state: "MISS" };
  const layers = [{ ...V0.layers[0], state: "MISS" }, origin];
  const { container } = renderReport(
    withLayers(layers, { cached: false, serving_layer: origin.layer_name, headline: "", headline_detail: "" }),
  );
  const bands = Array.from(container.querySelectorAll(".band")) as HTMLElement[];
  expect(bands[1]).toHaveClass("served-origin");
  expect(bands[1]).not.toHaveClass("served");
  expect(bands[1].textContent).toContain("Served by the origin, nothing cached");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Not cached. The origin served it.");
});

test("claims rows", () => {
  const gap = renderReport(withVerdict({ timing_check: GAP }));
  const claims = gap.container.querySelector(".claims") as HTMLElement;
  const delivered = within(claims).getByText("Delivered by").closest(".claim") as HTMLElement;
  expect(delivered.textContent).toContain("Akamai");
  expect(delivered.textContent).toContain("example-foods.com.edgekey.net");
  expect(within(delivered).getByRole("img", { name: "Confidence: high" })).toBeInTheDocument();
  const timing = within(claims).getByText("Timing").closest(".claim") as HTMLElement;
  expect(timing.textContent).toContain("Doesn't match the headers");
  expect(timing.textContent).toContain("timing gap");
  expect(within(timing).getByRole("img", { name: "Confidence: medium" })).toBeInTheDocument();
  gap.unmount();

  const insufficient = renderReport(withVerdict({ timing_check: { ...GAP, status: "insufficient", confidence: "low" } }));
  const t2 = within(insufficient.container.querySelector(".claims") as HTMLElement).getByText("Timing").closest(".claim") as HTMLElement;
  expect(t2.textContent).toContain("Not enough timing data");
  expect(within(t2).getByRole("img", { name: "Not rated" })).toBeInTheDocument();
  insufficient.unmount();

  const none = renderReport(withVerdict({ timing_check: undefined }));
  expect(within(none.container.querySelector(".claims") as HTMLElement).queryByText("Timing")).toBeNull();
});

test("old report renders with fallbacks", () => {
  const { container } = renderReport(akamaiReportLegacy);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Served from Apache Dispatcher.");
  const bands = Array.from(container.querySelectorAll(".band")) as HTMLElement[];
  expect(bands.length).toBeGreaterThan(0);
  for (const band of bands) expect(within(band).getByRole("img", { name: "Not rated" })).toBeInTheDocument();
  expect(bands[0].querySelector(".band-role")!.textContent).toBe("Edge cache");
});

// --- 1.3.0: measured, hosted, degraded/failed ----------------------------------

function withSamples(samples: unknown[]): Report {
  return { ...akamaiReport, samples_json: samples } as unknown as Report;
}

test("measured section", () => {
  renderReport(withSamples([timedSample(1), timedSample(2), timedSample(3)]));
  const section = screen.getByRole("heading", { name: "What the requests showed" }).closest("section") as HTMLElement;
  expect(within(section).getByText(/3 consecutive requests/)).toBeInTheDocument();
  const firstRow = section.querySelector("tbody tr th") as HTMLElement;
  expect(firstRow.textContent).toBe("Model's reading");
  expect(within(section).getByText("One round trip to the edge took 38.2 ms.")).toBeInTheDocument();
});

test("hosted summary", () => {
  const { container } = renderReport(akamaiReport);
  const hosted = container.querySelector(".hosted") as HTMLElement;
  expect(within(hosted).getByRole("heading", { name: "Where it's hosted" })).toBeInTheDocument();
  expect(within(hosted).getByText("Measured from Berlin, DE · Playwright runner")).toBeInTheDocument();
  const dns = within(hosted).getByText("DNS").parentElement as HTMLElement;
  expect(dns.textContent).toContain("www.example-foods.com");
  expect(dns.textContent).toContain("e1234.dscx.akamaiedge.net");
  const answered = within(hosted).getByText("Answered by").parentElement as HTMLElement;
  expect(answered.textContent).toContain("23.55.142.16");
  const route = within(hosted).getByText("Route").parentElement as HTMLElement;
  expect(route.textContent).toContain("7 hops");
  expect(route.textContent).toContain("Frankfurt");
  expect(route.textContent).toContain("6\u00a0ms"); // never breaks between number and unit
  expect(route.textContent).not.toContain("6.1");
  const disclosures = Array.from(hosted.querySelectorAll("details")) as HTMLDetailsElement[];
  expect(disclosures.map((d) => d.querySelector("summary")!.textContent)).toEqual(["Map and hop list", "Raw response headers"]);
  expect(disclosures.every((d) => !d.open)).toBe(true);
  expect(within(disclosures[0]).getByText("CDN detected")).toBeInTheDocument();
  expect(within(disclosures[0]).getByTestId("geomap")).toBeInTheDocument();
  expect(within(disclosures[0]).getByText("Access")).toBeInTheDocument();
});

test("hosted route when the trace failed", () => {
  const failed = {
    ...akamaiReport,
    traceroute_json: { tool: "mtr", hops: [], error: { type: "TraceroutePermissionError", message: "needs raw-socket permission" } },
  } as unknown as Report;
  const { container } = renderReport(failed);
  const route = within(container.querySelector(".hosted") as HTMLElement).getByText("Route").parentElement as HTMLElement;
  expect(route.textContent).toContain("Not traced");
  expect(route.textContent).toContain("needs raw-socket permission");
});

test("degraded and failed reports keep evidence and vantage", () => {
  const degraded = renderReport({ ...akamaiReport, verdict_json: { status: "unavailable", reason: "x" }, llm_json: null } as unknown as Report);
  expect(degraded.container.querySelector('[role="img"][aria-label^="Confidence"]')).toBeNull();
  expect(screen.getByRole("heading", { name: "What the requests showed" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Where it's hosted" })).toBeInTheDocument();
  expect(screen.getByText("Measured from Berlin, DE · Playwright runner")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "What to look at" })).toBeNull();
  expect(degraded.container.querySelector("tbody tr th")!.textContent).not.toBe("Model's reading");
  degraded.unmount();

  renderReport({ ...akamaiReport, status: "error", error: "no successful samples collected", verdict_json: null, llm_json: null } as unknown as Report);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Analysis failed");
  expect(screen.getByText("Measured from Berlin, DE · Playwright runner")).toBeInTheDocument();
});

// --- 1.3.0 final-review fixes ---------------------------------------------------

test("not cached + non-origin serving layer is blue and never says Hit", () => {
  const proxy: Layer = { ...V0.layers[2], state: "MISS" };
  const { container } = renderReport(
    withLayers([{ ...V0.layers[0], state: "MISS" }, proxy], { cached: false, serving_layer: proxy.layer_name, headline: "", headline_detail: "" }),
  );
  expect(container.querySelector(".band.served")).toBeNull();
  const band = container.querySelectorAll(".band")[1] as HTMLElement;
  expect(band).toHaveClass("served-origin");
  expect(band.textContent).toContain("Served the page, nothing cached");
  expect(band.textContent).not.toContain("Hit");
});

test("bands show the model's layer name and cache type, and the strata state the layer count", () => {
  const { container } = renderReport(akamaiReport);
  const band = container.querySelectorAll(".band")[2] as HTMLElement;
  expect(band.textContent).toContain("Apache Dispatcher");
  expect(band.textContent).toContain("disk cache");
  expect(screen.getByText("3 caching layers between you and the origin, by the model's count.")).toBeInTheDocument();
});

// --- 1.3.1: real-data report improvements ---------------------------------------

test("bands that share a vendor are named by layer, without repeating the cache type", () => {
  const { container } = renderReport(akamaiReport);
  const bands = Array.from(container.querySelectorAll(".band")) as HTMLElement[];
  expect(bands.map((b) => b.querySelector(".band-name")!.textContent)).toEqual([
    "Akamai Edge",
    "Akamai Shield",
    "Apache / AEM",
    "Adobe AEM",
  ]);
  expect(bands[0].querySelector(".band-detail")!.textContent).toBe("CDN edge cache");
  expect(bands[2].querySelector(".band-detail")!.textContent).toBe("Apache Dispatcher, disk cache");
});

const REACHED: TimingCheck = { ...GAP, status: "consistent", hidden_layer_suspected: false, probe_reached_origin: true };

test("the origin band shows the cache-bust request's time behind the edge", () => {
  const probe = { ...timedSample(4, true), timing: { connect_ms: null, tls_ms: null, ttfb_ms: 288.2, total_ms: 300, rtt_ms: null } };
  const samples = [timedSample(1), timedSample(2), timedSample(3), probe];
  const { container, unmount } = renderReport({ ...withVerdict({ timing_check: REACHED }), samples_json: samples } as unknown as Report);
  const bands = Array.from(container.querySelectorAll(".band")) as HTMLElement[];
  const origin = bands[bands.length - 1];
  expect(origin.querySelector(".band-measured")!.textContent).toBe("Cache-bust request: 250 ms behind the edge");
  expect(container.querySelectorAll(".band-measured")).toHaveLength(1);
  unmount();

  const none = renderReport({ ...withVerdict({ timing_check: REACHED }), samples_json: [timedSample(1), timedSample(2)] } as unknown as Report);
  expect(none.container.querySelector(".band-measured")).toBeNull();
});

test("the cache-bust line appears only when the model says the probe reached the origin (1.3.2)", () => {
  const probe = { ...timedSample(4, true), timing: { connect_ms: null, tls_ms: null, ttfb_ms: 61.6, total_ms: 70, rtt_ms: null } };
  const samples = [timedSample(1), timedSample(2), timedSample(3), probe];
  const measured = (timing_check: TimingCheck | undefined) => {
    const { container, unmount } = renderReport({ ...withVerdict({ timing_check }), samples_json: samples } as unknown as Report);
    const found = container.querySelector(".band-measured") !== null;
    unmount();
    return found;
  };
  expect(measured(REACHED)).toBe(true);
  // theguardian.com: the cache ignored the query string, so it never got there.
  expect(measured({ ...REACHED, probe_reached_origin: false })).toBe(false);
  expect(measured({ ...REACHED, probe_reached_origin: undefined })).toBe(false);
  expect(measured({ ...REACHED, status: "insufficient" })).toBe(false);
  expect(measured(undefined)).toBe(false);
});

test("hosted route prefers the header location when GeoIP disagrees", () => {
  const layers = V0.layers.map((l, i) => (i === 0 ? { ...l, location: "hhn1 (Frankfurt-Hahn)" } : l));
  const hostedRoute = (r: Report) => {
    const { container, unmount } = renderReport(r);
    const t = (within(container.querySelector(".hosted") as HTMLElement).getByText("Route").parentElement as HTMLElement).textContent ?? "";
    unmount();
    return t;
  };
  // The real hackaday.com case: anycast GeoIP put the last hop in San Francisco.
  const trace = akamaiReport.traceroute_json as { hops: { city: string }[] };
  const sf = { ...trace, hops: trace.hops.map((h, i) => (i === 6 ? { ...h, city: "San Francisco" } : h)) };
  const conflict = hostedRoute({ ...withLayers(layers), traceroute_json: sf } as unknown as Report);
  expect(conflict).toContain("7 hops, ending at hhn1 (Frankfurt-Hahn), 6\u00a0ms");
  expect(conflict).toContain("GeoIP says San Francisco");
  // A header location that contains the GeoIP city counts as agreement.
  expect(hostedRoute(withLayers(layers))).toContain("7 hops, ending in Frankfurt, 6\u00a0ms");

  // Agreeing locations (fixture: "Frankfurt" both ways) keep the plain line.
  const agree = hostedRoute(akamaiReport);
  expect(agree).toContain("7 hops, ending in Frankfurt, 6\u00a0ms");
  expect(agree).not.toContain("GeoIP");
});

test("hosted route says 1 hop", () => {
  const one = {
    ...akamaiReport,
    traceroute_json: { ...(akamaiReport.traceroute_json as object), hops: [(akamaiReport.traceroute_json as { hops: unknown[] }).hops[6]] },
  } as unknown as Report;
  const { container } = renderReport(one);
  const route = within(container.querySelector(".hosted") as HTMLElement).getByText("Route").parentElement as HTMLElement;
  expect(route.textContent).toContain("1 hop,");
});

// --- The model's reading: a long summary reads as points, a short one as prose --

test("a summary of three or more sentences renders as one point per sentence", () => {
  const llm = { ...(akamaiReport.llm_json as Record<string, unknown>) };
  llm["overall_summary"] = "Akamai fronts the page. Its hit/miss headers are stripped. Server time is around 130-170 ms. The edge is a passthrough.";
  const { container } = renderReport({ ...akamaiReport, llm_json: llm } as Report);
  const items = Array.from(container.querySelectorAll("ul.why li")).map((li) => li.textContent);
  expect(items).toEqual([
    "Akamai fronts the page.",
    "Its hit/miss headers are stripped.",
    "Server time is around 130-170 ms.",
    "The edge is a passthrough.",
  ]);
  expect(container.querySelector("p.why")).toBeNull();
});

test("a summary of one or two sentences stays a paragraph", () => {
  const llm = { ...(akamaiReport.llm_json as Record<string, unknown>) };
  llm["overall_summary"] = "Akamai fronts the page. Its hit/miss headers are stripped.";
  const { container } = renderReport({ ...akamaiReport, llm_json: llm } as Report);
  expect(container.querySelector("p.why")?.textContent).toBe("Akamai fronts the page. Its hit/miss headers are stripped.");
  expect(container.querySelector("ul.why")).toBeNull();
});
