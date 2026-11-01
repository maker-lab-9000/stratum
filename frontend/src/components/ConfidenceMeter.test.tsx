import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ConfidenceMeter } from "./ConfidenceMeter";

test("medium fills two bars, shows the word and an accessible label", () => {
  const { container } = render(<ConfidenceMeter level="medium" />);
  expect(container.querySelectorAll(".meter i.on")).toHaveLength(2);
  expect(screen.getByText("Medium")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Confidence: medium" })).toBeInTheDocument();
});

test("lg size adds meter-lg", () => {
  const { container } = render(<ConfidenceMeter level="high" size="lg" />);
  expect(container.querySelector(".meter-lg")).not.toBeNull();
  expect(container.querySelectorAll(".meter i.on")).toHaveLength(3);
});

test("unrated levels render a dash, never a default", () => {
  for (const level of [null, undefined, "moderate"]) {
    const { unmount } = render(<ConfidenceMeter level={level} />);
    expect(screen.getByRole("img", { name: "Not rated" }).textContent).toBe("—");
    expect(screen.queryByText("Low")).toBeNull();
    unmount();
  }
});

test("showWord={false} hides the word but keeps the label", () => {
  render(<ConfidenceMeter level="low" showWord={false} />);
  expect(screen.queryByText("Low")).toBeNull();
  expect(screen.getByRole("img", { name: "Confidence: low" })).toBeInTheDocument();
});
