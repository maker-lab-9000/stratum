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
  renderReport(akamaiReport);

  // Verdict tiles, user->origin order.
  expect(screen.getByText("Bypassed")).toBeInTheDocument();
  expect(screen.getByText("Apache Dispatcher")).toBeInTheDocument();
  expect(screen.getByText("Akamai")).toBeInTheDocument();

  // DNS panel: CDN detected + data-driven signature label.
  expect(screen.getByText("CDN detected")).toBeInTheDocument();
  expect(screen.getByText("example-foods.com.edgekey.net")).toBeInTheDocument();
  expect(screen.getAllByText("Akamai signature").length).toBeGreaterThan(0);

  // Geomap (Berlin -> Frankfurt both resolvable) rather than the strip fallback.
  expect(screen.getByTestId("geomap")).toBeInTheDocument();

  // Hop ladder (a middle hop + the edge anchor).
  expect(screen.getByText("62.155.241.18")).toBeInTheDocument();
  expect(screen.getByText(/Akamai Edge/)).toBeInTheDocument();

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
