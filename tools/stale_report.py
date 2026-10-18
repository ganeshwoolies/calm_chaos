"""Knowledge past its stale_after, and policies due within DUE_DAYS. Exits 1 when anything is stale, because a stale
policy stops every run that needs it.

    uv run python tools/stale_report.py knowledge
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.knowledge import DUE_DAYS, load_bundle, staleness


def report(root: Path, now: datetime | None = None) -> tuple[list[str], list[str]]:
    return staleness(load_bundle(root), now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", nargs="?", default="knowledge", type=Path)
    args = parser.parse_args()
    stale, due = report(args.bundle)
    for line in stale + due:
        print(line)
    print(f"{len(stale)} stale, {len(due)} policies due within {DUE_DAYS} days")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
