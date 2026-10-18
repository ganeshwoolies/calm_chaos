"""Copies of the knowledge bundle for tests: verified as a reviewer would verify them, or edited one key at a time."""

import shutil
from pathlib import Path
from typing import Any

import yaml

from app.knowledge import REPO_DIR, RESERVED_NAMES, split_frontmatter

REPO_BUNDLE = REPO_DIR / "knowledge"
TEST_VERIFICATION = [{"by": "human:test-reviewer", "at": "2026-10-01T00:00:00Z"}]


def edit_concept(root: Path, path: str, **changes: Any) -> None:
    """Sets frontmatter keys on one concept; a value of None removes the key."""
    file = root / path.lstrip("/")
    parsed = split_frontmatter(file.read_text(encoding="utf-8"))
    assert parsed, f"{path} has no frontmatter"
    meta, body = parsed
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    file.write_text(
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        + "---\n"
        + body,
        encoding="utf-8",
    )


def copy_bundle(dst: Path, verified: bool = True) -> Path:
    """The repository's bundle under dst; with verified, every concept stable and verified by a test reviewer."""
    shutil.copytree(REPO_BUNDLE, dst)
    if verified:
        for file in dst.rglob("*.md"):
            if file.name not in RESERVED_NAMES:
                edit_concept(
                    dst,
                    "/" + file.relative_to(dst).as_posix(),
                    status="stable",
                    verified=TEST_VERIFICATION,
                )
    return dst
