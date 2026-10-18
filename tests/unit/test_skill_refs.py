from tests.knowledge_copy import REPO_BUNDLE
from tools.gen_skill_refs import render_all


def test_generated_skill_files_match_the_bundle() -> None:
    stale = [
        str(path)
        for path, text in render_all(REPO_BUNDLE).items()
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]
    assert stale == [], "run: uv run python tools/gen_skill_refs.py"
