import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";

import { TopBar } from "./TopBar";

function at(path: string, ui: React.ReactNode) {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

test("brand + nav, with aria-current on the active route", () => {
  at("/history", <TopBar />);
  expect(screen.getByText("Stratum")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New analysis" })).toHaveAttribute("href", "/");
  const history = screen.getByRole("link", { name: "History" });
  expect(history).toHaveAttribute("href", "/history");
  expect(history).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "New analysis" })).not.toHaveAttribute("aria-current");
});

test("renders context and actions", () => {
  at("/", <TopBar context={<span>ctx-here</span>} actions={<button type="button">Act</button>} />);
  expect(screen.getByText("ctx-here")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Act" })).toBeInTheDocument();
});
