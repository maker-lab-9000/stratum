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
  children: ReactNode;
}

export function Table({ variant, head, className, children }: TableProps) {
  return (
    <div className="tbl-wrap">
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
