// Signal-bar confidence meter (1.3.0 redesign) — the one way to show how sure
// the model is about a claim. Three ascending bars in --accent: high 3,
// medium 2, low 1. An unrated claim renders "—" (never a default "Low").
const LEVELS = { high: 3, medium: 2, low: 1 } as const;
type Level = keyof typeof LEVELS;

const isLevel = (v: unknown): v is Level => v === "high" || v === "medium" || v === "low";
const word = (l: Level) => l[0].toUpperCase() + l.slice(1);

interface ConfidenceMeterProps {
  level: string | null | undefined;
  size?: "sm" | "lg";
  showWord?: boolean;
}

export function ConfidenceMeter({ level, size = "sm", showWord = true }: ConfidenceMeterProps) {
  if (!isLevel(level)) {
    return (
      <span className="meter-none" role="img" aria-label="Not rated">
        —
      </span>
    );
  }
  const filled = LEVELS[level];
  return (
    <span className={`meter-wrap meter-wrap-${size}`}>
      <span className={`meter meter-${size}`} role="img" aria-label={`Confidence: ${level}`}>
        {[1, 2, 3].map((n) => (
          <i key={n} className={n <= filled ? "on" : undefined} />
        ))}
      </span>
      {showWord && <span className="meter-word">{word(level)}</span>}
    </span>
  );
}
