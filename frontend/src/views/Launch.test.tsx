import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { createAnalysis, getModels, getProviderModels } from "../api/client";
import { Launch } from "./Launch";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (orig) => {
  const actual = (await orig()) as object;
  return { ...actual, useNavigate: () => navigateMock };
});
vi.mock("../api/client", () => ({
  getModels: vi.fn(),
  getProviderModels: vi.fn(),
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
  // By default the live list echoes the provider's static seed (no change).
  vi.mocked(getProviderModels)
    .mockReset()
    .mockImplementation(async (p: string) => ({
      provider: p,
      models: PROVIDERS.providers.find((x) => x.id === p)?.models ?? [],
    }));
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
  expect(navigateMock).toHaveBeenCalledWith("/runs/rep-123", { state: { requestCount: 4 } });
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

// --- Scenario 6: dynamic per-provider model listing (1.0.1) -------------------

test("selecting a provider fetches its live models and filters a large list", async () => {
  const user = userEvent.setup();
  // OpenRouter returns a large live list; Anthropic stays small.
  const bigList = Array.from({ length: 40 }, (_, i) => ({
    id: `vendor/model-${i}`,
    name: `Model ${i}`,
  }));
  bigList.push({ id: "anthropic/claude-opus-4-8", name: "Claude Opus 4.8 (via OR)" });
  vi.mocked(getProviderModels).mockImplementation(async (p: string) => ({
    provider: p,
    models: p === "openrouter" ? bigList : PROVIDERS.providers[0].models,
  }));

  await renderLoaded();
  // Anthropic (2 models incl. the one static) → no filter box yet.
  expect(screen.queryByLabelText("Filter models")).not.toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("Provider"), "openrouter");

  // The live list lands: a distinctive live-only model appears as an option.
  expect(await screen.findByRole("option", { name: "Model 7" })).toBeInTheDocument();
  expect(getProviderModels).toHaveBeenCalledWith("openrouter");

  // A large list gets a filter box that narrows the options.
  const filter = screen.getByLabelText("Filter models");
  await user.type(filter, "Model 33");
  expect(screen.getByRole("option", { name: "Model 33" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Model 7" })).not.toBeInTheDocument();
});

test("live models replace the static seed for the chosen model in the POST", async () => {
  const user = userEvent.setup();
  vi.mocked(getProviderModels).mockImplementation(async (p: string) => ({
    provider: p,
    models: p === "openrouter" ? [{ id: "x-ai/grok-4", name: "Grok 4" }] : PROVIDERS.providers[0].models,
  }));

  await renderLoaded();
  await user.selectOptions(screen.getByLabelText("Provider"), "openrouter");
  await screen.findByRole("option", { name: "Grok 4" });

  await user.type(screen.getByLabelText("Target URL"), "https://x.test/");
  await user.click(screen.getByRole("button", { name: /run analysis/i }));

  await waitFor(() => expect(createAnalysis).toHaveBeenCalled());
  const body = vi.mocked(createAnalysis).mock.calls[0][0];
  expect(body.provider).toBe("openrouter");
  expect(body.model).toBe("x-ai/grok-4"); // the live model, not a static default
});
