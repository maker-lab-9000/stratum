import type { ReactNode } from "react";

// Section eyebrow (e.g. "01 Network route"). `sub` is the smaller indented
// variant used for sub-sections.
interface EyebrowProps {
  step?: ReactNode;
  sub?: boolean;
  children: ReactNode;
}

export function Eyebrow({ step, sub, children }: EyebrowProps) {
  return (
    <div className={sub ? "eyebrow sub" : "eyebrow"}>
      {step != null && <span className="step">{step}</span>}
      {children}
    </div>
  );
}
