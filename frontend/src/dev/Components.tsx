// Visual reference gallery for every primitive state (T15 scenario 5). Served at
// /dev/components. Later tasks (T16–T20) build against these primitives.
import {
  Badge,
  Card,
  ConfBar,
  DegradedBanner,
  Eyebrow,
  Table,
  TableRow,
  Tile,
} from "../components";

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 8 }}>
      <Eyebrow sub>{title}</Eyebrow>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        {children}
      </div>
    </section>
  );
}

export function ComponentsGallery() {
  return (
    <main className="wrap" style={{ maxWidth: 1180, margin: "0 auto", padding: "24px" }}>
      <Eyebrow step="DS">Design system · primitives</Eyebrow>

      <Group title="Verdict tiles">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, width: "100%" }}>
          <Tile label="Cached" value="Yes" foot="…but only at one layer" status="hit">
            <ConfBar percent={92} label="LLM verdict · high" />
          </Tile>
          <Tile label="CDN cache" value="Bypassed" foot="both tiers MISS every request" status="warn" />
          <Tile label="Hosting / CDN" value="Akamai" foot="AS20940 · Frankfurt" status="accent" />
          <Tile label="CDN cache" value="Unknown" foot={<>evidence ambiguous <Badge variant="unverified" /></>} status="unknown" />
        </div>
      </Group>

      <Group title="Badge · pill / badge">
        <Badge variant="pill">4 requests · warmed</Badge>
        <Badge variant="pill" keep>
          Model <b>Claude Opus 4.8</b>
        </Badge>
        <Badge variant="badge">CDN detected</Badge>
      </Group>

      <Group title="Badge · tag / state (HIT green only)">
        <Badge variant="tag" tone="hit">HIT</Badge>
        <Badge variant="tag" tone="miss">MISS</Badge>
        <Badge variant="tag" tone="unknown">UNKNOWN</Badge>
        <Badge variant="state" tone="hit">served</Badge>
      </Group>

      <Group title="Badge · sev">
        <Badge variant="sev" tone="crit">critical</Badge>
        <Badge variant="sev" tone="warn">warning</Badge>
        <Badge variant="sev" tone="info">info</Badge>
      </Group>

      <Group title="Badge · bhv (behaviour)">
        <Badge variant="bhv" tone="served">SERVED</Badge>
        <Badge variant="bhv" tone="pass">PASS</Badge>
        <Badge variant="bhv" tone="fwd">FORWARDS</Badge>
        <Badge variant="bhv" tone="none">NONE</Badge>
        <Badge variant="bhv" tone="init">INIT</Badge>
        <Badge variant="bhv" tone="unknown">UNKNOWN</Badge>
        <Badge variant="bhv" tone="origin-serve">FROM ORIGIN</Badge>
      </Group>

      <Group title="unverified tag">
        <span>
          Apache Dispatcher <Badge variant="unverified" />
        </span>
      </Group>

      <section style={{ marginBottom: 8 }}>
        <Eyebrow sub>Findings (Card)</Eyebrow>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <Card severity="crit" title="CDN not caching" evidenceHeader="Age: 0" unverified>
            <p>Every request returns Age 0 with Cache-Control: no-store.</p>
          </Card>
          <Card severity="warn" title="Missing HSTS" evidenceHeader="Strict-Transport-Security">
            <p>No Strict-Transport-Security header on any sample.</p>
          </Card>
        </div>
      </section>

      <section style={{ marginBottom: 8 }}>
        <Eyebrow sub>Table · hops</Eyebrow>
        <Table variant="hops" head={["#", "Host", "State"]}>
          <TableRow>
            <td className="n">1</td>
            <td className="host">192.168.1.1</td>
            <td>ok</td>
          </TableRow>
          <TableRow state="timeout">
            <td className="n">2</td>
            <td>* * *</td>
            <td>—</td>
          </TableRow>
          <TableRow state="served">
            <td className="n">6</td>
            <td className="host">23.55.1.1</td>
            <td>edge</td>
          </TableRow>
        </Table>
      </section>

      <section style={{ marginBottom: 8 }}>
        <Eyebrow sub>Table · progression state strip</Eyebrow>
        <span className="strip">
          <i className="h" />
          <i className="m" />
          <i className="u" />
          <i />
        </span>
      </section>

      <DegradedBanner onRerun={() => undefined} />
    </main>
  );
}
