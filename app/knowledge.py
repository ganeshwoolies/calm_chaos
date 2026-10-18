"""The governed knowledge bundle: knowledge/, in Open Knowledge Format v0.2.

Reading follows the spec's consumer rules: unknown keys and types are kept, an absent status means stable, a bare
verified mapping is one event. Using is stricter: code and prompts take a concept only when it is stable, verified by a
human and not stale.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, PositiveInt, model_validator

logger = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parent.parent
RESERVED_NAMES = {"index.md", "log.md"}
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)


class PolicyUnavailable(RuntimeError):
    """A rule the desk needs is missing, unreadable, unverified or stale. The run stops; there is no fallback."""


def bundle_dir() -> Path:
    return Path(os.environ.get("PSD_KNOWLEDGE_DIR") or REPO_DIR / "knowledge")


def split_frontmatter(text: str) -> tuple[Any, str] | None:
    """(frontmatter, body), or None when the text does not start with a frontmatter block."""
    m = _FRONTMATTER.match(text)
    if not m:
        return None
    return yaml.safe_load(m.group(1)), m.group(2)


def as_instant(value: Any) -> datetime | None:
    """An ISO 8601 instant with a UTC offset, else None. A date or a time without an offset is not an instant."""
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else None
    return None


def content_hash(root: Path) -> str:
    """Hash over every file's path and bytes, so any edit, committed or not, changes it."""
    h = hashlib.sha256()
    for p in sorted(
        x for x in root.rglob("*") if x.is_file() and "__pycache__" not in x.parts
    ):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


@dataclass(frozen=True)
class Verification:
    by: str
    at: datetime | None


@dataclass(frozen=True)
class Concept:
    path: str
    meta: dict[str, Any]
    body: str

    @property
    def id(self) -> str:
        return self.path.removesuffix(".md")

    @property
    def type(self) -> str:
        return str(self.meta.get("type") or "")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.id)

    @property
    def status(self) -> str:
        return str(self.meta.get("status") or "stable")

    @property
    def verified(self) -> list[Verification]:
        raw = self.meta.get("verified") or []
        if isinstance(raw, dict):
            raw = [raw]
        return [
            Verification(by=str(v.get("by") or ""), at=as_instant(v.get("at")))
            for v in raw
            if isinstance(v, dict)
        ]

    @property
    def human_verifications(self) -> list[Verification]:
        return [v for v in self.verified if v.by.startswith("human:")]

    @property
    def trust_tier(self) -> str:
        if self.human_verifications:
            return "human-reviewed"
        return "machine-confirmed" if self.verified else "unverified"

    @property
    def stale_after(self) -> datetime | None:
        return as_instant(self.meta.get("stale_after"))

    def is_stale(self, now: datetime | None = None) -> bool:
        stale_after = self.stale_after
        return stale_after is not None and (now or datetime.now(UTC)) >= stale_after

    def unusable_reason(self, now: datetime | None = None) -> str | None:
        if self.status != "stable":
            return f"status is {self.status}"
        if not self.human_verifications:
            return "not verified by a human"
        if self.meta.get("stale_after") is not None and self.stale_after is None:
            return "stale_after is not an ISO 8601 instant with a UTC offset"
        if self.is_stale(now):
            return f"stale since {self.stale_after.isoformat()}"
        return None

    def usable(self, now: datetime | None = None) -> bool:
        return self.unusable_reason(now) is None


@dataclass(frozen=True)
class Bundle:
    root: Path
    concepts: dict[str, Concept]
    unreadable: dict[str, str]
    content_hash: str

    def get(self, path: str) -> Concept | None:
        return self.concepts.get(path)


def _signature(root: Path) -> tuple:
    return tuple(
        sorted(
            (p.relative_to(root).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
            for p in root.rglob("*")
            if p.is_file()
        )
    )


def load_bundle(root: Path | None = None) -> Bundle:
    root = (root or bundle_dir()).resolve()
    if not root.is_dir():
        return Bundle(root=root, concepts={}, unreadable={}, content_hash="none")
    return _load(root, _signature(root))


@lru_cache(maxsize=8)
def _load(root: Path, _signature: tuple) -> Bundle:
    concepts: dict[str, Concept] = {}
    unreadable: dict[str, str] = {}
    for file in sorted(root.rglob("*.md")):
        if file.name in RESERVED_NAMES:
            continue
        path = "/" + file.relative_to(root).as_posix()
        try:
            parsed = split_frontmatter(file.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as e:
            unreadable[path] = f"cannot be parsed: {e}"
            continue
        if parsed is None or not isinstance(parsed[0], dict):
            unreadable[path] = "has no YAML frontmatter mapping"
            continue
        meta, body = parsed
        if not meta.get("type"):
            unreadable[path] = "has no type"
            continue
        concepts[path] = Concept(path=path, meta=meta, body=body)
    for path, reason in unreadable.items():
        logger.warning("knowledge concept %s skipped: %s", path, reason)
    return Bundle(
        root=root,
        concepts=concepts,
        unreadable=unreadable,
        content_hash=content_hash(root),
    )


def knowledge_version(bundle: Bundle | None = None) -> str:
    """The commit the image was built from when set; locally, a hash of the bundle as it is on disk."""
    return os.environ.get("PSD_KNOWLEDGE_VERSION") or (
        "local-" + (bundle or load_bundle()).content_hash
    )


# A policy this close to its stale_after is listed as due, so it is verified again before runs start failing on it.
DUE_DAYS = 30


def staleness(
    bundle: Bundle | None = None, now: datetime | None = None
) -> tuple[list[str], list[str]]:
    """Concepts past stale_after, and policies due within DUE_DAYS, one line each."""
    now = now or datetime.now(UTC)
    stale, due = [], []
    for path, concept in sorted((bundle or load_bundle()).concepts.items()):
        stale_after = concept.stale_after
        if stale_after is None:
            continue
        if concept.is_stale(now):
            stale.append(f"{path}: stale since {stale_after.isoformat()}")
        elif concept.type == "Policy" and stale_after - now <= timedelta(days=DUE_DAYS):
            due.append(f"{path}: due {stale_after.isoformat()}")
    return stale, due


# Typed values. Code reads values only from these concepts, so each must be stable, human-verified and carry
# stale_after. Severity and hazard names are checked against the taxonomy in cross_check, not here.


class HazardType(BaseModel):
    id: str
    playbook: str | None = None


class HazardTaxonomy(BaseModel):
    categories: list[str] = Field(min_length=1)
    severity_order: list[str] = Field(min_length=1, description="Least to most severe")
    hazard_types: list[HazardType] = Field(min_length=1)


class RecallTarget(BaseModel):
    customers_messaged: PositiveInt | None
    shelves_clear: PositiveInt | None


class RecallResponse(BaseModel):
    severity_by_hazard: dict[str, str]
    targets_minutes: dict[str, RecallTarget]
    store_action_severities: list[str]
    checkout_block_severities: list[str]
    checkout_block_drop_needs_reason: bool
    exposure_days: PositiveInt
    order_lookback_days: PositiveInt


LabelAction = Literal[
    "hold", "supplier_notice", "qa_alert", "listing_check", "listing_fix"
]


class ListingEdit(BaseModel):
    field: Literal["allergens", "warnings", "marks", "origin"]
    op: Literal["add", "remove", "set_to"]


class LabelRule(BaseModel):
    id: str
    condition: str
    severity: str | None = None
    severity_from: str | None = None
    hazard_type: str | None = None
    hazard_from: str | None = None
    actions: list[LabelAction] = Field(min_length=1)
    listing: ListingEdit | None = None

    @model_validator(mode="after")
    def _one_source_each(self) -> "LabelRule":
        if (self.severity is None) == (self.severity_from is None):
            raise ValueError(f"{self.id}: give exactly one of severity, severity_from")
        if (self.hazard_type is None) == (self.hazard_from is None):
            raise ValueError(f"{self.id}: give exactly one of hazard_type, hazard_from")
        if ("listing_fix" in self.actions) != (self.listing is not None):
            raise ValueError(f"{self.id}: listing_fix and a listing edit go together")
        return self


class LabelTarget(BaseModel):
    holds_verified: PositiveInt | None
    listing_fixed: PositiveInt | None


class CatalogueMatch(BaseModel):
    max_distance: float = Field(gt=0, le=2)
    same_size_required: bool


class LabelRules(BaseModel):
    rules: list[LabelRule] = Field(min_length=1)
    min_legibility: float = Field(ge=0, le=1)
    catalogue_match: CatalogueMatch
    ingredients_min_similarity: float = Field(ge=0, le=1)
    candidate_severities: list[str]
    targets_minutes: dict[str, LabelTarget]


class WarningHazard(BaseModel):
    hazard_type: str
    severity_missing_on_pack: str


class NamedWarningHazard(WarningHazard):
    value: str


class WarningHazards(BaseModel):
    warnings: list[NamedWarningHazard]
    default: WarningHazard


class MatchRule(BaseModel):
    barcode_first: bool
    top_k: PositiveInt
    max_distance: float = Field(gt=0, le=2)
    ambiguity_gap: float = Field(ge=0)
    require_model_confirmation: bool


class IncidentHandling(BaseModel):
    dismiss_suppress_hours: PositiveInt


class ShelfCheckRule(BaseModel):
    clear_min_confidence: float = Field(gt=0, le=1)


class Allergens(BaseModel):
    names: list[str] = Field(min_length=1)
    groups: dict[str, list[str]] = {}


WARNING_HAZARDS = "/references/warning-hazards.md"

TYPED_CONCEPTS: dict[str, type[BaseModel]] = {
    "/policy/hazard-taxonomy.md": HazardTaxonomy,
    "/policy/recall-response.md": RecallResponse,
    "/policy/label-rules.md": LabelRules,
    "/policy/match-rule.md": MatchRule,
    "/policy/incident-handling.md": IncidentHandling,
    "/policy/shelf-check.md": ShelfCheckRule,
    WARNING_HAZARDS: WarningHazards,
    "/references/allergens.md": Allergens,
}


def cross_check(values: dict[str, BaseModel]) -> list[str]:
    """Names one typed concept uses that another must define."""
    tax = values.get("/policy/hazard-taxonomy.md")
    if not isinstance(tax, HazardTaxonomy):
        return ["/policy/hazard-taxonomy.md is needed to check the other policies"]
    severities = set(tax.severity_order)
    hazards = {h.id for h in tax.hazard_types}
    problems: list[str] = []
    if len(severities) != len(tax.severity_order):
        problems.append("/policy/hazard-taxonomy.md: severity_order repeats a name")
    if len(hazards) != len(tax.hazard_types):
        problems.append("/policy/hazard-taxonomy.md: hazard_types repeats an id")

    def check(path: str, what: str, names: set[str], allowed: set[str]) -> None:
        if names - allowed:
            problems.append(
                f"{path}: {what} not in the taxonomy: {sorted(names - allowed)}"
            )

    recall = values.get("/policy/recall-response.md")
    if isinstance(recall, RecallResponse):
        path = "/policy/recall-response.md"
        if set(recall.severity_by_hazard) != hazards:
            problems.append(
                f"{path}: severity_by_hazard must name every hazard type exactly: {sorted(hazards)}"
            )
        check(path, "severities", set(recall.severity_by_hazard.values()), severities)
        if set(recall.targets_minutes) != severities:
            problems.append(f"{path}: targets_minutes must name every severity")
        check(
            path,
            "checkout block severities",
            set(recall.checkout_block_severities),
            severities,
        )
        check(
            path,
            "store action severities",
            set(recall.store_action_severities),
            severities,
        )

    labels = values.get("/policy/label-rules.md")
    if isinstance(labels, LabelRules):
        path = "/policy/label-rules.md"
        ids = [r.id for r in labels.rules]
        if len(set(ids)) != len(ids):
            problems.append(f"{path}: rule ids repeat")
        check(
            path,
            "severities",
            {r.severity for r in labels.rules if r.severity},
            severities,
        )
        check(
            path,
            "hazard types",
            {r.hazard_type for r in labels.rules if r.hazard_type},
            hazards,
        )
        for r in labels.rules:
            for ref in (r.severity_from, r.hazard_from):
                if ref and ref != WARNING_HAZARDS:
                    problems.append(
                        f"{path}: {r.id} refers to {ref}; only {WARNING_HAZARDS} is supported"
                    )
        check(
            path, "candidate severities", set(labels.candidate_severities), severities
        )
        if set(labels.targets_minutes) != severities:
            problems.append(f"{path}: targets_minutes must name every severity")

    warnings = values.get(WARNING_HAZARDS)
    if isinstance(warnings, WarningHazards):
        entries = [*warnings.warnings, warnings.default]
        check(
            WARNING_HAZARDS, "hazard types", {w.hazard_type for w in entries}, hazards
        )
        check(
            WARNING_HAZARDS,
            "severities",
            {w.severity_missing_on_pack for w in entries},
            severities,
        )
    return problems


def typed_values(
    bundle: Bundle,
    paths: list[str],
    now: datetime | None = None,
    require_usable: bool = True,
) -> dict[str, BaseModel]:
    """The typed values of each concept, raising PolicyUnavailable for one that is missing, unusable or invalid."""
    values: dict[str, BaseModel] = {}
    for path in paths:
        concept = bundle.get(path)
        if concept is None:
            reason = bundle.unreadable.get(path, "is missing")
            raise PolicyUnavailable(f"{path} {reason}")
        if require_usable and (reason := concept.unusable_reason(now)):
            raise PolicyUnavailable(f"{path} cannot be used: {reason}")
        try:
            values[path] = TYPED_CONCEPTS[path].model_validate(concept.meta)
        except ValueError as e:
            raise PolicyUnavailable(f"{path} has invalid values: {e}") from e
    if problems := cross_check(values):
        raise PolicyUnavailable("; ".join(problems))
    return values


def for_incident(
    playbook: str | None,
    supplier_id: str,
    product_id: str,
    store_ids: list[str],
    bundle: Bundle | None = None,
    now: datetime | None = None,
) -> list[Concept]:
    """Usable knowledge for one incident: the hazard's playbook, any promoted notes on its supplier, product and
    first three stores, and promoted coordinator practice. Unusable or absent concepts are left out; prompt knowledge
    is background, never a gate."""
    bundle = bundle or load_bundle()
    paths = [
        *([playbook] if playbook else []),
        f"/learned/suppliers/{supplier_id}.md",
        f"/learned/products/{product_id}.md",
        *(f"/learned/stores/{s}.md" for s in store_ids[:3]),
        "/learned/playbook/coordinator-practice.md",
    ]
    shown = []
    for path in paths:
        concept = bundle.get(path)
        if concept is None:
            continue
        if reason := concept.unusable_reason(now):
            logger.info("knowledge %s left out of the prompt: %s", path, reason)
            continue
        shown.append(concept)
    return shown


def render(concepts: list[Concept]) -> str:
    if not concepts:
        return "none: no verified knowledge applies to this incident"
    parts = []
    for c in concepts:
        verifier = c.human_verifications[-1]
        when = verifier.at.date().isoformat() if verifier.at else "undated"
        stale = c.stale_after.date().isoformat() if c.stale_after else "no expiry"
        parts.append(
            f"--- {c.path}: {c.title} ({c.type}; verified by {verifier.by} on {when}; stale after {stale})\n"
            f"{c.body.strip()}"
        )
    return "<KNOWLEDGE verified>\n" + "\n\n".join(parts) + "\n</KNOWLEDGE>"
