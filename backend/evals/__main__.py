"""CLI for the eval corpus.

    uv run --env-file ../.env python -m evals capture <report link> --name <case>
    uv run --env-file ../.env python -m evals run --model <provider:model> [--model …] [--case <name> …]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from evals.capture import CaptureError, capture, non_2xx_summary
from evals.case import CASES_DIR, CaseError, load_case, load_cases
from evals.runner import RUNS_DIR, Analyze, SetupError, parse_model_spec, run_eval, write_results
from evals.table import render_table


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="freeze a finished report into a case file")
    cap.add_argument("link", help="report link, e.g. http://localhost:8000/reports/<id>")
    cap.add_argument("--name", required=True, help="case name ([a-z0-9-]+)")

    run = sub.add_parser("run", help="replay cases through one or more models")
    run.add_argument("--model", action="append", required=True, metavar="PROVIDER:MODEL",
                     help="repeatable, e.g. anthropic:claude-opus-4-8")
    run.add_argument("--case", action="append", metavar="NAME", help="repeatable; default: all cases")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    analyze: Analyze | None = None,
    is_configured: Callable[[str], bool] | None = None,
    cases_dir: Path = CASES_DIR,
    runs_dir: Path = RUNS_DIR,
    env: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "capture":
            path = asyncio.run(capture(
                args.link, args.name, directory=cases_dir,
                env=os.environ if env is None else env,
            ))
            print(f"captured: {path}")
            blocked = non_2xx_summary(load_case(path).evidence["samples"])
            if blocked:
                print(f"warning: no sample returned 2xx ({blocked}) — the evidence may be a block "
                      "page or redirect; check it before writing an answer key", file=sys.stderr)
            print("next: fill in \"expected\" (serving / chain) if you know the real setup — "
                  "see evals/README.md")
            return 0

        models = [parse_model_spec(m) for m in args.model]
        cases = load_cases(cases_dir, args.case)
        if analyze is None or is_configured is None:
            from app.llm.registry import get_provider
            from app.pipeline.analyze import make_llm_analyze

            analyze = analyze or make_llm_analyze()
            is_configured = is_configured or (lambda p: get_provider(p) is not None)
        started = datetime.now(UTC)
        run = asyncio.run(run_eval(
            cases, models, analyze=analyze, is_configured=is_configured,
            progress=lambda line: print(line, file=sys.stderr, flush=True),
        ))
        print(render_table(cases, [m.label for m in models], run.outcomes))
        print(f"results: {write_results(run, models, runs_dir, now=started)}")
        return 0
    except (CaseError, SetupError, CaptureError) as exc:
        message = " ".join(str(exc).split())
        print(f"error: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
