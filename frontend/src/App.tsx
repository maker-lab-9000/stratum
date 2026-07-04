import { ComponentsGallery } from "./dev/Components";

// T15 scaffold: the design-system gallery is reachable at /dev/components (no
// router yet — T16 introduces routing). The real Launch/Report/History views
// land in T16–T20.
export default function App() {
  if (typeof window !== "undefined" && window.location.pathname === "/dev/components") {
    return <ComponentsGallery />;
  }
  return (
    <main className="wrap" style={{ maxWidth: 1180, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontFamily: "var(--disp)" }}>Stratum</h1>
      <p style={{ color: "var(--mid)" }}>
        Cache &amp; delivery analyzer. Visit <code>/dev/components</code> for the design system.
      </p>
    </main>
  );
}
