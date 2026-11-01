"""Plain-text expected-vs-actual table (no third-party dependency).

Per case: an ``expected`` row, then one row per model. Cells wider than their
column wrap onto continuation lines — nothing is truncated. Scores count only
cases that define the dimension; observed cases carry no marks.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence

from evals.case import Case
from evals.score import NONE_TEXT, Outcome, expected_texts

MAX_LINE = 158  # keep every line under 160 chars for typical names
SERVING_MAX = 36
CHAIN_MIN = 24
GAP = "  "


def _mark(ok: bool | None) -> str:
    return "" if ok is None else (" ✓" if ok else " ✗")


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_on_hyphens=False) or [""]


def render_table(
    cases: Sequence[Case],
    model_labels: Sequence[str],
    outcomes: Mapping[tuple[str, str], Outcome],
    notes: Mapping[tuple[str, str], str] | None = None,
) -> str:
    """``notes`` (1.4.0): an extra note per (case, label) row, e.g. the live
    investigate summary; joined to the unverified note when both apply."""
    # rows: (case, model, serving cell, chain cell, note)
    blocks: list[list[tuple[str, str, str, str, str]]] = []
    for case in cases:
        exp_serving, exp_chain = expected_texts(case.expected)
        rows = [(case.name, "expected", exp_serving, exp_chain, "")]
        for label in model_labels:
            out = outcomes[(case.name, label)]
            parts = [f"⚠ {out.unverified} unverified"] if out.unverified else []
            if notes and notes.get((case.name, label)):
                parts.append(notes[(case.name, label)])
            note = " · ".join(parts)
            rows.append(("", label, out.serving_text + _mark(out.serving_ok),
                         out.chain_text + _mark(out.chain_ok), note))
        blocks.append(rows)

    all_rows = [r for block in blocks for r in block]
    case_w = max([len("case")] + [len(r[0]) for r in all_rows])
    model_w = max([len("model"), len("expected")] + [len(r[1]) for r in all_rows])
    serving_w = min(SERVING_MAX, max([len("serving layer")] + [len(r[2]) for r in all_rows]))
    note_w = max([0] + [len(r[4]) for r in all_rows])
    fixed = case_w + model_w + serving_w + len(GAP) * (4 if note_w else 3) + note_w
    chain_w = min(max([len("chain")] + [len(r[3]) for r in all_rows]),
                  max(CHAIN_MIN, MAX_LINE - fixed))

    def emit(row: tuple[str, str, str, str, str]) -> list[str]:
        case, model, serving, chain, note = row
        s_lines, c_lines = _wrap(serving, serving_w), _wrap(chain, chain_w)
        lines = []
        for k in range(max(len(s_lines), len(c_lines))):
            cells = [
                (case if k == 0 else "").ljust(case_w),
                (model if k == 0 else "").ljust(model_w),
                (s_lines[k] if k < len(s_lines) else "").ljust(serving_w),
                (c_lines[k] if k < len(c_lines) else "").ljust(chain_w),
            ]
            if note_w:
                cells.append(note if k == 0 else "")
            lines.append(GAP.join(cells).rstrip())
        return lines

    out: list[str] = emit(("case", "model", "serving layer", "chain", ""))
    out.append("-" * min(MAX_LINE, case_w + model_w + serving_w + chain_w + len(GAP) * 3))
    for i, block in enumerate(blocks):
        if i:
            out.append("")
        for row in block:
            out.extend(emit(row))

    out.append("")
    for i, label in enumerate(model_labels):
        serving = _score(cases, outcomes, label, "serving")
        chain = _score(cases, outcomes, label, "chain")
        out.append(GAP.join([
            ("score" if i == 0 else "").ljust(case_w),
            label.ljust(model_w),
            f"serving {serving}   chain {chain}",
        ]).rstrip())
    return "\n".join(out) + "\n"


def _score(cases: Sequence[Case], outcomes, label: str, dimension: str) -> str:
    marks = [
        getattr(outcomes[(case.name, label)], f"{dimension}_ok") for case in cases
    ]
    scored = [m for m in marks if m is not None]
    if not scored:
        return NONE_TEXT
    return f"{sum(scored)}/{len(scored)}"
