"""House rules for the knowledge bundle, stricter than Open Knowledge Format v0.2 itself.

The workflow reads the bundle as a tolerant OKF consumer; this is the producer-side gate that keeps our own bundle to
the conventions the desk relies on. Prints one line per problem and exits 1 when there is any.

    uv run python tools/okf_validate.py knowledge
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.knowledge import (
    TYPED_CONCEPTS,
    as_instant,
    cross_check,
    load_bundle,
    split_frontmatter,
)

TYPES = {
    "BigQuery Table",
    "Metric",
    "Attested Computation",
    "Policy",
    "Playbook",
    "Reference",
    "Supplier Note",
    "Product Note",
    "Store Note",
}
STATUSES = {"draft", "stable", "deprecated"}
HUMAN_VERIFIED_WHEN_STABLE = ("/policy/", "/computations/", "/learned/")
NEEDS_SOURCES = ("/policy/", "/learned/")
NEEDS_STALE_AFTER = ("/learned/",)
PLAYBOOK_HEADINGS = ("# Trigger", "# Steps")

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]]+)\](?!:)")
_LOG_HEADING = re.compile(r"^## (.*)$", re.MULTILINE)


def _strip_code(body: str) -> str:
    return re.sub(r"```.*?```", "", body, flags=re.DOTALL)


def _check_links(root: Path, file: Path, body: str) -> list[str]:
    problems = []
    for target in _LINK.findall(_strip_code(body)):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        target = target.split("#", 1)[0]
        resolved = (
            root / target.lstrip("/")
            if target.startswith("/")
            else file.parent / target
        )
        if not resolved.resolve().is_file():
            problems.append(f"broken link {target}")
    return problems


def _check_concept(root: Path, path: str, meta: dict, body: str) -> list[str]:
    problems = []
    typed = path in TYPED_CONCEPTS
    concept_type = meta.get("type")
    if concept_type not in TYPES:
        problems.append(f"type {concept_type!r} is not one of {sorted(TYPES)}")
    for key in ("title", "description", "tags", "status"):
        if not meta.get(key):
            problems.append(f"missing {key}")
    tags = meta.get("tags")
    if tags and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        problems.append("tags must be a list of strings")
    status = meta.get("status")
    if status and status not in STATUSES:
        problems.append(f"status {status!r} is not one of {sorted(STATUSES)}")

    needs_stale_after = (
        typed or concept_type == "Policy" or path.startswith(NEEDS_STALE_AFTER)
    )
    if "stale_after" in meta and as_instant(meta["stale_after"]) is None:
        problems.append(
            "stale_after must be an ISO 8601 instant with a UTC offset, e.g. 2027-04-30T00:00:00Z"
        )
    elif needs_stale_after and "stale_after" not in meta:
        problems.append("missing stale_after")

    verified = meta.get("verified") or []
    if isinstance(verified, dict):
        verified = [verified]
    if not isinstance(verified, list):
        problems.append("verified must be a list of {by, at}")
        verified = []
    for v in verified:
        if (
            not isinstance(v, dict)
            or not v.get("by")
            or as_instant(v.get("at")) is None
        ):
            problems.append(
                "each verified entry needs by and at, at as an instant with a UTC offset"
            )
    humans = [
        v
        for v in verified
        if isinstance(v, dict) and str(v.get("by", "")).startswith("human:")
    ]
    needs_human = typed or path.startswith(HUMAN_VERIFIED_WHEN_STABLE)
    if meta.get("status", "stable") == "stable" and needs_human and not humans:
        problems.append("stable here needs a verified entry by a human:<id>")

    generated = meta.get("generated")
    if generated is not None and (
        not isinstance(generated, dict)
        or not generated.get("by")
        or ("at" in generated and as_instant(generated["at"]) is None)
    ):
        problems.append("generated needs by, and at as an instant with a UTC offset")

    sources = meta.get("sources") or []
    if path.startswith(NEEDS_SOURCES) and not sources:
        problems.append("missing sources")
    source_ids = set()
    for s in sources if isinstance(sources, list) else []:
        if not isinstance(s, dict) or not s.get("resource"):
            problems.append("each source needs a resource")
        elif s.get("id"):
            if s["id"] in source_ids:
                problems.append(f"source id {s['id']} repeats")
            source_ids.add(s["id"])
    for label in sorted(set(_FOOTNOTE_REF.findall(body)) - source_ids):
        problems.append(f"footnote [^{label}] cites no source id")

    if concept_type == "BigQuery Table" and not meta.get("resource"):
        problems.append("a BigQuery Table needs resource")
    if concept_type == "Playbook":
        for heading in PLAYBOOK_HEADINGS:
            if not re.search(rf"^{re.escape(heading)}\s*$", body, re.MULTILINE):
                problems.append(f"a Playbook needs a '{heading}' section")
    if concept_type == "Attested Computation":
        problems += _check_computation(root, meta)
    return problems


def _bundle_file(root: Path, ref: object) -> bool:
    return isinstance(ref, str) and (root / ref.lstrip("/")).is_file()


def _check_computation(root: Path, meta: dict) -> list[str]:
    problems = []
    if not meta.get("runtime"):
        problems.append("an Attested Computation needs runtime")
    parameters = meta.get("parameters")
    if not isinstance(parameters, list) or not all(
        isinstance(p, dict) and {"name", "type", "required"} <= set(p)
        for p in parameters
    ):
        problems.append("parameters must be a list of {name, type, required}")
    if not _bundle_file(root, meta.get("computation")):
        problems.append(
            f"computation {meta.get('computation')!r} is not a file in the bundle"
        )
    executor = meta.get("executor")
    if not isinstance(executor, dict) or not _bundle_file(
        root, executor.get("resource")
    ):
        problems.append("executor.resource must name a file in the bundle")
    if not isinstance(executor, dict) or not executor.get("receipt"):
        problems.append("executor.receipt must list the receipt fields")
    attester = meta.get("attester")
    if not isinstance(attester, dict) or not _bundle_file(
        root, attester.get("resource")
    ):
        problems.append("attester.resource must name a file in the bundle")
    return problems


def _check_index(root: Path, file: Path) -> list[str]:
    text = file.read_text(encoding="utf-8")
    parsed = split_frontmatter(text)
    if file.parent != root:
        return ["an index.md below the root has no frontmatter"] if parsed else []
    if not parsed or parsed[0] != {"okf_version": "0.2"}:
        return [
            'the root index.md declares exactly okf_version: "0.2" in its frontmatter'
        ]
    return []


def _check_log(file: Path) -> list[str]:
    problems = []
    headings = _LOG_HEADING.findall(file.read_text(encoding="utf-8"))
    dates = []
    for heading in headings:
        try:
            dates.append(date.fromisoformat(heading.strip()))
        except ValueError:
            problems.append(f"log heading {heading!r} is not a YYYY-MM-DD date")
    if dates != sorted(dates, reverse=True):
        problems.append("log entries are not newest first")
    return problems


def validate(root: Path) -> list[str]:
    root = root.resolve()
    if not (root / "index.md").is_file():
        return [f"{root}: no root index.md"]
    bundle = load_bundle(root)
    problems = [f"{path}: {reason}" for path, reason in bundle.unreadable.items()]
    linked: set[Path] = set()

    for file in sorted(root.rglob("*.md")):
        path = "/" + file.relative_to(root).as_posix()
        if file.name == "index.md":
            problems += [f"{path}: {p}" for p in _check_index(root, file)]
            parsed = split_frontmatter(file.read_text(encoding="utf-8"))
            body = parsed[1] if parsed else file.read_text(encoding="utf-8")
            problems += [f"{path}: {p}" for p in _check_links(root, file, body)]
            for target in _LINK.findall(body):
                if not re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    t = target.split("#", 1)[0]
                    linked.add(
                        (
                            root / t.lstrip("/")
                            if t.startswith("/")
                            else file.parent / t
                        ).resolve()
                    )
        elif file.name == "log.md":
            problems += [f"{path}: {p}" for p in _check_log(file)]

    values: dict[str, BaseModel] = {}
    for path, concept in bundle.concepts.items():
        file = root / path.lstrip("/")
        found = _check_concept(root, path, concept.meta, concept.body)
        found += _check_links(root, file, concept.body)
        if file.resolve() not in linked:
            found.append("not listed in any index.md")
        if path in TYPED_CONCEPTS:
            try:
                values[path] = TYPED_CONCEPTS[path].model_validate(concept.meta)
            except ValidationError as e:
                found += [
                    f"{'.'.join(str(x) for x in err['loc']) or 'value'}: {err['msg']}"
                    for err in e.errors()
                ]
        problems += [f"{path}: {p}" for p in found]

    missing = sorted(set(TYPED_CONCEPTS) - set(bundle.concepts))
    problems += [f"{path}: missing (code reads its values)" for path in missing]
    if not missing and len(values) == len(TYPED_CONCEPTS):
        problems += cross_check(values)
        taxonomy = values["/policy/hazard-taxonomy.md"]
        for hazard in taxonomy.hazard_types:  # type: ignore[attr-defined]
            if hazard.playbook and bundle.get(hazard.playbook) is None:
                problems.append(
                    f"/policy/hazard-taxonomy.md: {hazard.id} names playbook {hazard.playbook}, which does not exist"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", nargs="?", default="knowledge", type=Path)
    args = parser.parse_args()
    problems = validate(args.bundle)
    for problem in problems:
        print(problem)
    print(
        f"{len(problems)} problem(s) in {args.bundle}"
        if problems
        else f"{args.bundle}: valid"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
