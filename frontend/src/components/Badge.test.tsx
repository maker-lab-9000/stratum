import { render } from "@testing-library/react";
import { expect, test } from "vitest";

import { Badge } from "./Badge";

function classOf(node: HTMLElement) {
  return (node.firstChild as HTMLElement).className;
}

test("renders each variant with the mockup class", () => {
  expect(classOf(render(<Badge variant="pill">x</Badge>).container)).toBe("pill");
  expect(classOf(render(<Badge variant="pill" keep>x</Badge>).container)).toBe("pill keep");
  expect(classOf(render(<Badge variant="badge">x</Badge>).container)).toBe("badge");
  expect(classOf(render(<Badge variant="tag" tone="hit">HIT</Badge>).container)).toBe("tag hit");
  expect(classOf(render(<Badge variant="tag" tone="miss">MISS</Badge>).container)).toBe("tag miss");
  expect(classOf(render(<Badge variant="sev" tone="crit">c</Badge>).container)).toBe("sev crit");
  expect(classOf(render(<Badge variant="bhv" tone="served">S</Badge>).container)).toBe("bhv served");
  expect(classOf(render(<Badge variant="bhv" tone="fwd">F</Badge>).container)).toBe("bhv fwd");
  expect(classOf(render(<Badge variant="state" tone="unknown">U</Badge>).container)).toBe("tag unknown");
});

test("unknown tone (dashed grey) and unverified (amber dashed) render", () => {
  expect(classOf(render(<Badge variant="tag" tone="unknown">U</Badge>).container)).toBe("tag unknown");
  expect(classOf(render(<Badge variant="bhv" tone="unknown">U</Badge>).container)).toBe("bhv unknown");
  const uv = render(<Badge variant="unverified" />);
  expect(classOf(uv.container)).toBe("unverified");
  expect(uv.container.textContent).toBe("unverified");
});

test("structural pill/badge carry no status tone (no green leak)", () => {
  expect(classOf(render(<Badge variant="pill">x</Badge>).container)).not.toMatch(/hit|served/);
  expect(classOf(render(<Badge variant="badge">x</Badge>).container)).not.toMatch(/hit|served/);
});
