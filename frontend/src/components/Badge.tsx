import type { ReactNode } from "react";

// Badge unifies the mockup's small-label families: pill / badge / tag / sev /
// bhv / state / unverified. Green (hit/served/origin-serve visual) is only ever
// reachable via a status tone — never a structural default.
export type BadgeVariant =
  | "pill"
  | "badge"
  | "tag"
  | "sev"
  | "bhv"
  | "state"
  | "unverified";

export type BadgeTone =
  | "hit"
  | "miss"
  | "unknown"
  | "crit"
  | "warn"
  | "info"
  | "served"
  | "pass"
  | "none"
  | "init"
  | "fwd"
  | "origin-serve";

interface BadgeProps {
  variant: BadgeVariant;
  tone?: BadgeTone;
  keep?: boolean; // pill only: stays visible on mobile (.pill.keep)
  className?: string;
  children?: ReactNode;
}

// "state" is an alias for the tag family (a standalone HIT/MISS/UNKNOWN pill).
const BASE: Record<BadgeVariant, string> = {
  pill: "pill",
  badge: "badge",
  tag: "tag",
  sev: "sev",
  bhv: "bhv",
  state: "tag",
  unverified: "unverified",
};

export function Badge({ variant, tone, keep, className, children }: BadgeProps) {
  const classes = [BASE[variant]];
  if (tone) classes.push(tone);
  if (keep && variant === "pill") classes.push("keep");
  if (className) classes.push(className);
  return (
    <span className={classes.join(" ")}>
      {children ?? (variant === "unverified" ? "unverified" : null)}
    </span>
  );
}
