import type { Segment } from "./types";

// 2–4 route segments narrated by the LLM (§5.3, §8.1.3). Access/Transit are
// neutral; the CDN segment is accented.
function segClass(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("access")) return "segc access";
  if (n.includes("transit")) return "segc transit";
  if (n.includes("cdn")) return "segc cdn";
  if (n.includes("origin")) return "segc cdn";
  return "segc";
}

const Check = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

export function SegmentNarration({ segments }: { segments: Segment[] }) {
  if (!segments || segments.length === 0) return null;
  return (
    <div className="seg-narrate">
      {segments.map((s, i) => (
        <div key={i} className={segClass(s.segment)}>
          <div className="sh">
            <span className="sname">{s.segment}</span>
            <span className="srange">{s.hop_range}</span>
          </div>
          <p>{s.description}</p>
          {s.corroboration && (
            <div className="corrob">
              <Check />
              {s.corroboration}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
