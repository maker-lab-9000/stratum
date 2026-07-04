import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { createAnalysis, getModels } from "../api/client";
import { Launch } from "./Launch";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (orig) => {
  const actual = (await orig()) as object;
  return { ...actual, useNavigate: () => navigateMock };
});
vi.mock("../api/client", () => ({
  getModels: vi.fn(),
  createAnalysis: vi.fn(),
}));

const PROVIDERS = {
  providers: [
    { id: "anthropic", name: "Anthropic", models: [{ id: "claude-opus-4-8", name: "Claude Opus 4.8" }] },
    { id: "openrouter", name: "OpenRouter", models: [{ id: "openai/gpt-5", name: "GPT-5" }] },
  ],
};

beforeEach(() => {
  navigateMock.mockReset();
  vi.mocked(getModels).mockReset().mockResolvedValue(PROVIDERS);
  vi.mocked(createAnalysis).mockReset().mockResolvedValue({ id: "rep-123" });
});

async function renderLoaded() {
  render(<Launch />);
  await screen.findByRole("option", { name: "Anthropic" });
}

// --- Scenario 1 ---------------------------------------------------------------

test("valid URL + defaults -> exact POST body + navigates to live run", async () => {
  const user = userEvent.setup();
  await renderLoaded();

  await user.type(screen.getByLabelText("Target URL"), "https://www.example.com/");
  await user.click(screen.getByRole("button", { name: /run analysis/i }));

  await waitFor(() => expect(createAnalysis).toHaveBeenCalledTimes(1));
  expect(createAnalysis).toHaveBeenCalledWith({
    url: "https://www.example.com/",
    provider: "anthropic",
    model: "claude-opus-4-8",
    options: {
      request_count: 4,
      interval_ms: 0,
      warm: true,
      extra_request_headers: {},
      geo_hint: null,
    },
  });
  expect(navigateMock).toHaveBeenCalledWith("/runs/rep-123");
});

// --- Scenario 2 ---------------------------------------------------------------

test("invalid URL -> inline error, no request", async () => {
  const user = userEvent.setup();
  await renderLoaded();

  await user.type(screen.getByLabelText("Target URL"), "not a url");
  await user.click(screen.getByRole("button", { name: /run analysis/i }));

  expect(screen.getByRole("alert")).toHaveTextContent(/absolute http/i);
  expect(createAnalysis).not.toHaveBeenCalled();
  expect(navigateMock).not.toHaveBeenCalled();
});

// --- Scenario 3 ---------------------------------------------------------------

test("no providers -> actionable empty state, Run disabled", async () => {
  vi.mocked(getModels).mockResolvedValue({ providers: [] });
  render(<Launch />);

  expect(await screen.findByText(/ANTHROPIC_API_KEY/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /run analysis/i })).toBeDisabled();
});

// --- Scenario 4 ---------------------------------------------------------------

test("advanced values appear in POST options", async () => {
  const user = userEvent.setup();
  await renderLoaded();

  await user.type(screen.getByLabelText("Target URL"), "https://x.test/");
  await user.click(screen.getByText("Advanced"));

  const requests = screen.getByLabelText("Requests");
  await user.clear(requests);
  await user.type(requests, "8");
  const interval = screen.getByLabelText("Interval (ms)");
  await user.clear(interval);
  await user.type(interval, "500");
  await user.type(screen.getByLabelText("header 1 name"), "X-Debug");
  await user.type(screen.getByLabelText("header 1 value"), "1");

  await user.click(screen.getByRole("button", { name: /run analysis/i }));

  await waitFor(() => expect(createAnalysis).toHaveBeenCalled());
  const body = vi.mocked(createAnalysis).mock.calls[0][0];
  expect(body.options.request_count).toBe(8);
  expect(body.options.interval_ms).toBe(500);
  expect(body.options.extra_request_headers).toEqual({ "X-Debug": "1" });
});

// --- Scenario 5 ---------------------------------------------------------------

test("keyboard: URL -> provider tab order; Enter submits", async () => {
  const user = userEvent.setup();
  await renderLoaded();

  const urlInput = screen.getByLabelText("Target URL");
  urlInput.focus();
  expect(urlInput).toHaveFocus();

  await user.tab();
  expect(screen.getByLabelText("Provider")).toHaveFocus();

  await user.type(urlInput, "https://kbd.test/");
  urlInput.focus();
  await user.keyboard("{Enter}");

  await waitFor(() => expect(createAnalysis).toHaveBeenCalled());
});
