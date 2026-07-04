import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import App from "./App";

// The root route renders the Launch view.
test("renders the launch view at /", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network in test"));
  render(<App />);
  expect(screen.getByRole("button", { name: /run analysis/i })).toBeInTheDocument();
  // Model fetch fails -> empty state settles (awaited to avoid act warnings).
  expect(await screen.findByText(/ANTHROPIC_API_KEY/)).toBeInTheDocument();
});
