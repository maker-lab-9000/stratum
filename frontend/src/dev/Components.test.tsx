import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ComponentsGallery } from "./Components";

test("gallery renders every primitive group without error", () => {
  render(<ComponentsGallery />);
  expect(screen.getByText("Design system · primitives")).toBeInTheDocument();
  // A sampling of primitive states are present.
  expect(screen.getByText("Bypassed")).toBeInTheDocument(); // warn tile
  expect(screen.getAllByText("UNKNOWN").length).toBeGreaterThan(0); // unknown tags
  expect(screen.getByText("Verdict unavailable.")).toBeInTheDocument(); // degraded banner
});
