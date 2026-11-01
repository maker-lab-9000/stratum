import { createContext, useContext } from "react";
import type { ReactNode } from "react";

// One Table primitive backs the hop ladder, layer breakdown, and header
// progression (§8). The variant picks the mockup's table styling; TableRow maps
// a semantic `state` to the variant-appropriate row class (the "served" row is
// styled differently per table, so the mapping lives here in one place).
export type TableVariant = "hops" | "layers" | "prog";
export type RowState = "served" | "timeout" | "asnGroup" | "private";

const VariantCtx = createContext<TableVariant>("hops");

const ROW_CLASS: Record<TableVariant, Partial<Record<RowState, string>>> = {
  hops: { served: "edge-row", timeout: "timeout", asnGroup: "asn-group", private: "private" },
  layers: { served: "row-served" },
  prog: { served: "served-row" },
};

interface TableProps {
  variant: TableVariant;
  head?: ReactNode[];
  className?: string;
  label?: string;
  children: ReactNode;
}

// Accessible names for the scroll region per variant (overridable via `label`).
const DEFAULT_LABEL: Record<TableVariant, string> = {
  hops: "Traceroute hops",
  layers: "Cache layers",
  prog: "Measured values per request",
};

export function Table({ variant, head, className, label, children }: TableProps) {
  // The wrapper scrolls sideways on narrow screens, so it is a focusable,
  // labelled region — keyboard users can scroll it (axe scrollable-region-focusable).
  return (
    <div className="tbl-wrap" tabIndex={0} role="region" aria-label={label ?? DEFAULT_LABEL[variant]}>
      <table className={className ? `${variant} ${className}` : variant}>
        {head && (
          <thead>
            <tr>
              {head.map((cell, i) => (
                <th key={i}>{cell}</th>
              ))}
            </tr>
          </thead>
        )}
        <VariantCtx.Provider value={variant}>
          <tbody>{children}</tbody>
        </VariantCtx.Provider>
      </table>
    </div>
  );
}

interface TableRowProps {
  state?: RowState;
  className?: string;
  children: ReactNode;
}

export function TableRow({ state, className, children }: TableRowProps) {
  const variant = useContext(VariantCtx);
  const stateClass = state ? ROW_CLASS[variant][state] : undefined;
  const cls = [stateClass, className].filter(Boolean).join(" ");
  return <tr className={cls || undefined}>{children}</tr>;
}
