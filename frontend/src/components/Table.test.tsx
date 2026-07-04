import { render } from "@testing-library/react";
import { expect, test } from "vitest";

import { Table, TableRow } from "./Table";

test("renders the variant table + header, and maps row states per variant", () => {
  const { container } = render(
    <Table variant="hops" head={["#", "Host", "State"]}>
      <TableRow>
        <td>1</td>
      </TableRow>
      <TableRow state="served">
        <td>edge</td>
      </TableRow>
      <TableRow state="timeout">
        <td>* * *</td>
      </TableRow>
    </Table>,
  );

  const table = container.querySelector("table")!;
  expect(table.className).toBe("hops");
  expect(container.querySelectorAll("thead th")).toHaveLength(3);

  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].className).toBe(""); // plain row -> no state class
  expect(rows[1].className).toBe("edge-row"); // served row in the hops table
  expect(rows[2].className).toBe("timeout");
});

test("served row is styled per-variant (layers vs prog)", () => {
  const layers = render(
    <Table variant="layers">
      <TableRow state="served">
        <td>x</td>
      </TableRow>
    </Table>,
  );
  expect(layers.container.querySelector("tbody tr")!.className).toBe("row-served");

  const prog = render(
    <Table variant="prog">
      <TableRow state="served">
        <th scope="row">x</th>
      </TableRow>
    </Table>,
  );
  expect(prog.container.querySelector("tbody tr")!.className).toBe("served-row");
});
