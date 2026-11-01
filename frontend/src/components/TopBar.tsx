import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

// The one top bar every view shares (1.3.0 redesign): brand left, page context
// in the middle, the main nav and the page's own actions on the right.
export function TopBar({ context, actions }: { context?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="appbar">
      <Link className="appbar-brand" to="/">
        Stratum
      </Link>
      {context && <div className="appbar-context">{context}</div>}
      <nav className="appbar-nav" aria-label="Main">
        <NavLink to="/" end>
          New analysis
        </NavLink>
        <NavLink to="/history">History</NavLink>
      </nav>
      {actions && <div className="appbar-actions">{actions}</div>}
    </header>
  );
}
