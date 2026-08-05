from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parsed_argv = tuple(sys.argv[1:] if argv is None else argv)
    original_argv0 = sys.argv[0]
    sys.argv[0] = "rbi"
    try:
        from rural_basic_income.worker.cli import main as worker_main

        return worker_main(parsed_argv, prog="rbi")
    finally:
        sys.argv[0] = original_argv0
