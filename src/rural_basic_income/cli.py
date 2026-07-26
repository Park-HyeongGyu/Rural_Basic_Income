from __future__ import annotations

from collections.abc import Sequence

from rural_basic_income.worker.cli import main as worker_main


def main(argv: Sequence[str] | None = None) -> int:
    return worker_main(argv, prog="rbi")
