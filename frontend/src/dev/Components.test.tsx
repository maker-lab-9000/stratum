import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";

import { ComponentsGallery } from "./Components";

test("gallery renders the current primitives", () => {
  render(
    <MemoryRouter>
      <ComponentsGallery />
    </MemoryRouter>,
  );
  expect(screen.getByRole("heading", { name: "Design system" })).toBeInTheDocument();
  for (const level of ["high", "medium", "low"]) {
    expect(screen.getAllByRole("img", { name: `Confidence: ${level}` }).length).toBeGreaterThanOrEqual(2);
  }
  expect(screen.getByRole("img", { name: "Not rated" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "History" })).toBeInTheDocument(); // TopBar
  expect(screen.getByText("timing gap")).toBeInTheDocument();
  expect(screen.getByText("unverified")).toBeInTheDocument();
  expect(screen.queryByText("Verdict unavailable.")).toBeNull(); // old banner gone
});
