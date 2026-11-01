// Visual reference for the current primitives (1.3.0 redesign). Served at
// /dev/components. Every shared pattern renders through one of these.
import { Badge, ConfidenceMeter, Table, TableRow, TopBar } from "../components";

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2>{title}</h2>
      <div className="gallery-row">{children}</div>
    </section>
  );
}

export function ComponentsGallery() {
  return (
    <main className="page">
      <TopBar context={<span className="url">https://www.example.com/</span>} />
      <h1>Design system</h1>
      <p className="lede">The primitives every view is built from. Tokens come from the mockup.</p>

      <Group title="Confidence meter">
        <ConfidenceMeter level="high" size="lg" />
        <ConfidenceMeter level="medium" size="lg" />
        <ConfidenceMeter level="low" size="lg" />
        <ConfidenceMeter level="high" />
        <ConfidenceMeter level="medium" />
        <ConfidenceMeter level="low" />
        <ConfidenceMeter level={null} />
      </Group>

      <Group title="Tags">
        <Badge variant="tag" tone="hit">HIT</Badge>
        <Badge variant="tag" tone="miss">MISS</Badge>
        <Badge variant="tag" tone="unknown">UNKNOWN</Badge>
        <span>
          Apache Dispatcher <Badge variant="unverified" />
        </span>
        <span>
          Fastly <Badge variant="timing-gap" />
        </span>
      </Group>

      <Group title="Table">
        <Table variant="prog" head={["Request", "1", "2"]}>
          <TableRow>
            <th scope="row">Age</th>
            <td>613</td>
            <td>614</td>
          </TableRow>
        </Table>
      </Group>
    </main>
  );
}
