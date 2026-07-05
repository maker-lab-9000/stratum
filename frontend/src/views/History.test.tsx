import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

import { deleteAnalysis, listAnalyses, type Report } from "../api/client";
import { History } from "./History";

vi.mock("../api/client", () => ({
  listAnalyses: vi.fn(),
  deleteAnalysis: vi.fn(),
}));

function makeReport(i: number, over: Partial<Report> = {}): Report {
  return {
    id: `rep-${i}`,
    url: `https://site${i}.example.com/page`,
    created_at: "2026-07-01T10:00:00Z",
    status: "done",
    provider: "anthropic",
    model: "claude-opus-4-8",
    vantage: null,
    verdict_json: {
      cached: true,
      provider: "Akamai",
      serving_layer: "Akamai Edge",
      layer_count_to_origin: 2,
      validation: { ok: true, flags: [] },
    },
    dns_json: null,
    traceroute_json: null,
    samples_json: null,
    llm_json: {
      security_findings: [{ severity: "warning", title: "w", description: "", evidence_header: "H" }],
      performance_findings: [{ severity: "critical", title: "c", description: "", evidence_header: "H: v" }],
    },
    error: null,
    domain: `site${i}.example.com`,
    has_critical: true,
    ...over,
  };
}

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function renderHistory(entry = "/history") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LocationProbe />
      <Routes>
        <Route path="/history" element={<History />} />
        <Route path="/reports/:id" element={<div>REPORT VIEW</div>} />
        <Route path="/" element={<div>LAUNCH VIEW</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(listAnalyses).mockReset().mockResolvedValue({ reports: [] });
  vi.mocked(deleteAnalysis).mockReset().mockResolvedValue();
});

// --- Scenario 1: 25 rows render; UNKNOWN verdict shows a grey dot ------------

test("renders the full list; a degraded/UNKNOWN verdict shows a grey dot", async () => {
  const reports = Array.from({ length: 25 }, (_, i) => makeReport(i));
  // Row 0 is degraded -> unknown dot; row 1 is a bypass -> neutral dot.
  reports[0] = makeReport(0, { verdict_json: { status: "unavailable", reason: "x" }, llm_json: null });
  reports[1] = makeReport(1, {
    verdict_json: { cached: false, provider: "Akamai", serving_layer: "Origin", layer_count_to_origin: 1 },
  });
  vi.mocked(listAnalyses).mockResolvedValue({ reports });

  renderHistory();
  await waitFor(() => expect(screen.getAllByText(/site\d+\.example\.com/).length).toBe(25));

  const dots = document.querySelectorAll(".vdot");
  expect(dots).toHaveLength(25);
  expect(dots[0]).toHaveClass("unknown"); // degraded
  expect(dots[0]).not.toHaveClass("hit");
  expect(dots[1]).toHaveClass("miss"); // bypass, neutral (not green, not amber)
  expect(dots[2]).toHaveClass("hit"); // cached
});

// --- Scenario 2: filters combine + mirror to the URL (shareable) -------------

test("domain + has-critical filters combine and the URL reflects them", async () => {
  const user = userEvent.setup();
  renderHistory();
  await waitFor(() => expect(listAnalyses).toHaveBeenCalled());

  await user.type(screen.getByLabelText("Filter by domain"), "shop");
  await user.click(screen.getByLabelText("Has critical findings"));

  await waitFor(() =>
    expect(listAnalyses).toHaveBeenLastCalledWith({ domain: "shop", hasCritical: true }),
  );
  expect(screen.getByTestId("loc")).toHaveTextContent("domain=shop");
  expect(screen.getByTestId("loc")).toHaveTextContent("critical=1");
});

test("a shared URL with filters deep-loads pre-filtered (survives refresh)", async () => {
  renderHistory("/history?domain=news&critical=1");
  await waitFor(() =>
    expect(listAnalyses).toHaveBeenCalledWith({ domain: "news", hasCritical: true }),
  );
  expect(screen.getByLabelText("Filter by domain")).toHaveValue("news");
  expect(screen.getByLabelText("Has critical findings")).toBeChecked();
});

// --- Scenario 3: row opens the report permalink ------------------------------

test("clicking a row routes to the report permalink", async () => {
  const user = userEvent.setup();
  vi.mocked(listAnalyses).mockResolvedValue({ reports: [makeReport(7)] });
  renderHistory();

  const link = await screen.findByRole("link", { name: "https://site7.example.com/page" });
  expect(link).toHaveAttribute("href", "/reports/rep-7");
  await user.click(link);
  expect(screen.getByText("REPORT VIEW")).toBeInTheDocument();
  expect(screen.getByTestId("loc")).toHaveTextContent("/reports/rep-7");
});

// --- Scenario 4: delete with confirm -----------------------------------------

test("delete asks to confirm; Yes removes the row + calls the API, No does nothing", async () => {
  const user = userEvent.setup();
  vi.mocked(listAnalyses).mockResolvedValue({ reports: [makeReport(1), makeReport(2)] });
  renderHistory();
  await screen.findByText("https://site1.example.com/page");

  // Cancel path: confirm then No — nothing deleted.
  await user.click(screen.getByRole("button", { name: "Delete analysis for https://site1.example.com/page" }));
  await user.click(screen.getByRole("button", { name: "No" }));
  expect(deleteAnalysis).not.toHaveBeenCalled();
  expect(screen.getByText("https://site1.example.com/page")).toBeInTheDocument();

  // Confirm path: Delete then Yes — API called, row gone.
  await user.click(screen.getByRole("button", { name: "Delete analysis for https://site1.example.com/page" }));
  await user.click(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(deleteAnalysis).toHaveBeenCalledWith("rep-1"));
  await waitFor(() => expect(screen.queryByText("https://site1.example.com/page")).not.toBeInTheDocument());
  expect(screen.getByText("https://site2.example.com/page")).toBeInTheDocument();
});

// --- Scenario 5: empty state invites action ----------------------------------

test("empty history shows an invitation linking to Launch", async () => {
  renderHistory();
  const empty = await screen.findByTestId("history-empty");
  expect(within(empty).getByRole("link", { name: /run your first one/i })).toHaveAttribute("href", "/");
});

test("empty under active filters offers to clear them (not the first-run copy)", async () => {
  renderHistory("/history?domain=none");
  const empty = await screen.findByTestId("history-empty");
  expect(empty).toHaveTextContent(/match these filters/i);
});
