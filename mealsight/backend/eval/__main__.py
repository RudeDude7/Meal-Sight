"""CLI entry point: python -m eval [dimension1] [dimension2] [dimension3] [--limit N] [--sampled]

Examples:
    python -m eval                          # both dimensions, full case set
    python -m eval dimension1                # just dimension1
    python -m eval dimension2 --sampled      # cheap routine check, ~1/3 of cases
    python -m eval --limit 5                 # cap case count on every selected dimension
"""

from __future__ import annotations

import argparse
import asyncio

from eval.runner import DIMENSIONS, run_eval


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MealSight eval framework.")
    parser.add_argument(
        "dimensions",
        nargs="*",
        # No argparse `choices` here: with nargs="*" argparse validates the empty
        # list (no dimension named) against them and crashes. Checked in main().
        help=f"Which dimension(s) to run, from {', '.join(DIMENSIONS)} (default: all).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap the number of cases/images per dimension."
    )
    parser.add_argument(
        "--sampled",
        action="store_true",
        help="Dimension 2 only: run a cheap ~1/3 sample instead of the full case set.",
    )
    return parser.parse_args()


def main() -> None:
    parser_args = _parse_args()
    unknown = [d for d in parser_args.dimensions if d not in DIMENSIONS]
    if unknown:
        raise SystemExit(f"unknown dimension(s): {', '.join(unknown)} (choose from {', '.join(DIMENSIONS)})")
    args = parser_args
    dimensions = tuple(args.dimensions) if args.dimensions else DIMENSIONS
    scorecard = asyncio.run(run_eval(dimensions=dimensions, case_limit=args.limit, sampled=args.sampled))
    raise SystemExit(0 if scorecard.passed else 1)


if __name__ == "__main__":
    main()
