import type { ReactNode } from "react";

// Topology node icons keyed by layer `role` (§8.4 / spec §4.1) — never by
// vendor. The deterministic code knows nothing about who a layer is; it only
// draws the shape the LLM's role classification asks for. An unrecognised role
// falls back to the neutral "unknown" glyph.
const ICONS: Record<string, ReactNode> = {
  client: (
    <>
      <rect x="3" y="4" width="18" height="13" rx="1.5" />
      <path d="M8 20h8M12 17v3" />
    </>
  ),
  edge: (
    <>
      <path d="M12 2a9 9 0 100 18 9 9 0 000-18z" />
      <path d="M3 12h18M12 3c2.5 2.5 2.5 13.5 0 18M12 3c-2.5 2.5-2.5 13.5 0 18" />
    </>
  ),
  shield: (
    <>
      <path d="M5 9l7-5 7 5v9a1 1 0 01-1 1H6a1 1 0 01-1-1z" />
      <path d="M9 19v-6h6v6" />
    </>
  ),
  security: <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" />,
  load_balancer: (
    <>
      <circle cx="12" cy="5" r="2.2" />
      <circle cx="5" cy="19" r="2.2" />
      <circle cx="19" cy="19" r="2.2" />
      <path d="M12 7.2v3M12 10.2c0 3-7 3-7 6.6M12 10.2c0 3 7 3 7 6.6" />
    </>
  ),
  reverse_proxy: (
    <>
      <rect x="3" y="4" width="18" height="6" rx="1" />
      <rect x="3" y="14" width="18" height="6" rx="1" />
      <path d="M7 7h.01M7 17h.01" />
    </>
  ),
  app_cache: (
    <>
      <rect x="3" y="4" width="18" height="6" rx="1" />
      <rect x="3" y="14" width="18" height="6" rx="1" />
      <path d="M7 7h.01M7 17h.01" />
    </>
  ),
  origin: (
    <>
      <path d="M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z" />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </>
  ),
  unknown: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 013.9-2c1.2.8 1 2.3-.4 3-.7.4-1 .8-1 1.6M12 16.5h.01" />
    </>
  ),
};

// Render the glyph for a role. Falls back to the "unknown" shape.
export function RoleIcon({ role }: { role: string }) {
  return <svg viewBox="0 0 24 24">{ICONS[role] ?? ICONS.unknown}</svg>;
}
