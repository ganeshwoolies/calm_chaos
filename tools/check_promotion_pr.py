"""The pull-request check's promotion rule: a promotion pull request changes only knowledge/learned/.

    git diff --name-only origin/main...HEAD | uv run python tools/check_promotion_pr.py --branch promote/<id>

A pull request from a promote/ branch, which only the desk's promotion step opens, may merge without an owner's
review (.github/CODEOWNERS), so it must not change anything else. Any other branch passes this check. Exits 1 and names
each path outside knowledge/learned/ when a promotion pull request strays.
"""

import argparse
import sys

LEARNED = "knowledge/learned/"
PROMOTION_PREFIX = "promote/"


def strays(branch: str, paths: list[str]) -> list[str]:
    if not branch.startswith(PROMOTION_PREFIX):
        return []
    return [p for p in paths if p and not p.startswith(LEARNED)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    paths = [line.strip() for line in sys.stdin if line.strip()]
    outside = strays(args.branch, paths)
    for path in outside:
        print(f"a promotion pull request may not change {path}")
    if args.branch.startswith(PROMOTION_PREFIX) and not paths:
        print(
            "no changed paths were read; the check cannot pass a promotion pull request blind"
        )
        return 1
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
