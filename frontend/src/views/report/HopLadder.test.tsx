import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { HopLadder } from "./HopLadder";
import type { Hop } from "./types";

function hop(n: number, over: Partial<Hop> = {}): Hop {
  return {
    n,
    ip: `10.0.0.${n}`,
    rdns: `hop-${n}.net`,
    asn: 3320,
    org: "Deutsche Telekom",
    city: "Berlin",
    rtt_ms: 5,
    private: false,
    unresponsive: false,
    hint: null,
    ...over,
  };
}

// 22 hops: 3 timeouts, a 9-hop AS3320 run, then Akamai edge.
function bigRoute(): Hop[] {
  const hops: Hop[] = [];
  hops.push(hop(1, { private: true, asn: null, org: null, rtt_ms: 0.4 }));
  for (let n = 2; n <= 10; n++) hops.push(hop(n, { asn: 3320, rtt_ms: n })); // 9-hop DTAG run
  hops.push(hop(11, { unresponsive: true, ip: null, rdns: null, asn: null }));
  hops.push(hop(12, { unresponsive: true, ip: null, rdns: null, asn: null }));
  hops.push(hop(13, { asn: 6695, org: "DE-CIX", city: "Frankfurt", rtt_ms: 20 }));
  for (let n = 14; n <= 19; n++) hops.push(hop(n, { asn: 1299, org: "Arelion", rtt_ms: 40 }));
  hops.push(hop(20, { unresponsive: true, ip: null, rdns: null, asn: null }));
  hops.push(hop(21, { asn: 20940, org: "Akamai", city: "Frankfurt", rtt_ms: 88 }));
  hops.push(hop(22, { asn: 20940, org: "Akamai", city: "Frankfurt", rtt_ms: 90, ip: "23.55.1.1" }));
  return hops;
}

test("9-hop same-ASN run collapses; expands on click; RTT bars normalized", async () => {
  const user = userEvent.setup();
  render(<HopLadder hops={bigRoute()} verdict={null} />);

  // The 9-hop AS3320 run is collapsed into a summary row.
  const group = screen.getByText(/9 hops · click to expand/);
  expect(group).toBeInTheDocument();
  // Its member hops are not individually rendered yet.
  expect(screen.queryByText("hop-5.net")).not.toBeInTheDocument();

  await user.click(group);
  expect(screen.getByText("hop-5.net")).toBeInTheDocument();

  // Timeout rows render as * * *.
  expect(screen.getAllByText("* * *").length).toBe(3);

  // RTT bars are normalized to the route max (90 ms -> ~100px); a small hop is much shorter.
  const bars = document.querySelectorAll(".lat .bar");
  const widths = [...bars].map((b) => parseFloat((b as HTMLElement).style.width));
  expect(Math.max(...widths)).toBeGreaterThanOrEqual(95);
  expect(Math.min(...widths)).toBeLessThan(20);
});

test("edge row is flagged and normalized", () => {
  render(<HopLadder hops={bigRoute()} verdict={{ provider: "Akamai" } as never} />);
  const edgeCell = screen.getByText(/Akamai Edge/);
  expect(edgeCell).toBeInTheDocument();
  const row = edgeCell.closest("tr")!;
  expect(row).toHaveClass("edge-row");
  expect(within(row).getByText("23.55.1.1")).toBeInTheDocument();
});
