// Placeholder views — replaced by T17 (LiveRun), T18 (Report), T20 (History).
import { Link, useParams } from "react-router-dom";

function Stub({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: 24 }}>
      <div className="brand" style={{ marginBottom: 16 }}>
        <span className="dot" />
        <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
          Stratum
        </Link>
      </div>
      <h1 style={{ fontFamily: "var(--disp)" }}>{title}</h1>
      {children}
    </main>
  );
}

export function LiveRun() {
  const { id } = useParams();
  return (
    <Stub title="Live run">
      <p style={{ color: "var(--mid)" }}>
        Analysis <code style={{ fontFamily: "var(--mono)" }}>{id}</code> — live stepper lands in T17.
      </p>
    </Stub>
  );
}

export function Report() {
  const { id } = useParams();
  return (
    <Stub title="Report">
      <p style={{ color: "var(--mid)" }}>
        Report <code style={{ fontFamily: "var(--mono)" }}>{id}</code> — rendered in T18/T19.
      </p>
    </Stub>
  );
}

export function History() {
  return (
    <Stub title="History">
      <p style={{ color: "var(--mid)" }}>History table lands in T20.</p>
    </Stub>
  );
}
