import { ConfidenceMeter } from "../../components";
import type { Recommendation } from "./types";

// Recommendations (1.4.0): what else would settle the open questions when the
// model's own requests were not enough. Rendered only when non-empty.
export function Recommendations({ items }: { items: Recommendation[] }) {
  if (items.length === 0) return null;
  return (
    <section className="recs">
      <h2>Recommendations</h2>
      <p className="lede">What else could settle the open questions, in the model's view.</p>
      <ol className="rec-list">
        {items.map((r, i) => (
          <li key={i} className="rec">
            <div className="rec-body">
              <h3 className="rec-title">{r.action}</h3>
              <p>{r.reason}</p>
            </div>
            <div className="rec-rate">
              <ConfidenceMeter level={r.confidence} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
