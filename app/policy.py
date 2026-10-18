"""Desk policy, read from the knowledge bundle (knowledge/policy, knowledge/references) each time a run needs it.

Nothing else in the code holds a severity, time target or threshold. current() raises PolicyUnavailable when a policy
concept is missing, invalid, unverified or stale, and the run stops: there is no fallback value.
"""

from dataclasses import dataclass
from datetime import datetime

from app.knowledge import (
    WARNING_HAZARDS,
    Bundle,
    HazardTaxonomy,
    IncidentHandling,
    LabelRule,
    LabelRules,
    MatchRule,
    PolicyUnavailable,
    RecallResponse,
    ShelfCheckRule,
    WarningHazard,
    WarningHazards,
    knowledge_version,
    load_bundle,
    typed_values,
)
from app.schemas import EvidencePack, LabelFinding

__all__ = ["Policy", "PolicyUnavailable", "build", "current", "shelf_rule"]

TAXONOMY = "/policy/hazard-taxonomy.md"
RECALL = "/policy/recall-response.md"
LABELS = "/policy/label-rules.md"
MATCH = "/policy/match-rule.md"
HANDLING = "/policy/incident-handling.md"
# Loaded on its own by shelf_rule: until it is reviewed only shelf photos wait, not drafting or approval.
SHELF = "/policy/shelf-check.md"
POLICY_PATHS = [TAXONOMY, RECALL, LABELS, MATCH, HANDLING, WARNING_HAZARDS]

# The policy concepts the drafter sees for each kind; its sources_used may cite these.
SHOWN_POLICY = {
    "recall": [RECALL, TAXONOMY],
    "label": [LABELS, WARNING_HAZARDS, TAXONOMY],
}

_ACTION_WORDS = {
    "hold": "hold the lot",
    "supplier_notice": "supplier notice",
    "qa_alert": "QA alert",
    "listing_check": "check the listing",
    "listing_fix": "listing fix",
}


@dataclass(frozen=True)
class Policy:
    version: str
    taxonomy: HazardTaxonomy
    recall: RecallResponse
    labels: LabelRules
    warnings: WarningHazards
    match: MatchRule
    handling: IncidentHandling

    @property
    def severity_order(self) -> list[str]:
        return self.taxonomy.severity_order

    def max_severity(self, severities: list[str]) -> str:
        order = self.severity_order
        return max(severities, key=order.index) if severities else order[0]

    def playbook(self, hazard_type: str) -> str | None:
        return next(
            (h.playbook for h in self.taxonomy.hazard_types if h.id == hazard_type),
            None,
        )

    def check_evidence(self, ev: EvidencePack) -> None:
        if ev.hazard_type not in {h.id for h in self.taxonomy.hazard_types}:
            raise ValueError(f"hazard type {ev.hazard_type!r} is not in {TAXONOMY}")
        if ev.product.category not in self.taxonomy.categories:
            raise ValueError(f"category {ev.product.category!r} is not in {TAXONOMY}")

    def recall_severity(self, hazard_type: str) -> str:
        if hazard_type not in self.recall.severity_by_hazard:
            raise ValueError(f"hazard type {hazard_type!r} has no severity in {RECALL}")
        return self.recall.severity_by_hazard[hazard_type]

    def checkout_block(self, severity: str) -> bool:
        return severity in self.recall.checkout_block_severities

    def recall_store_actions(self, severity: str) -> bool:
        return severity in self.recall.store_action_severities

    def label_rule(self, rule_id: str) -> LabelRule:
        for rule in self.labels.rules:
            if rule.id == rule_id:
                return rule
        raise ValueError(f"label rule {rule_id!r} is not in {LABELS}")

    def _warning(self, value: str) -> WarningHazard:
        for w in self.warnings.warnings:
            if w.value.casefold() == value.casefold():
                return w
        return self.warnings.default

    def finding_severity(self, finding: LabelFinding) -> str:
        rule = self.label_rule(finding.rule)
        if rule.severity:
            return rule.severity
        return self._warning(finding.value).severity_missing_on_pack

    def finding_hazard(self, finding: LabelFinding) -> str:
        rule = self.label_rule(finding.rule)
        if rule.hazard_type:
            return rule.hazard_type
        return self._warning(finding.value).hazard_type

    def finding_for(self, rule_id: str, field: str, value: str) -> LabelFinding:
        """A label difference as a finding, with the severity, hazard and actions its rule gives."""
        rule = self.label_rule(rule_id)
        warning = self._warning(value)
        return LabelFinding(
            rule=rule_id,
            field=field,
            value=value,
            severity=rule.severity or warning.severity_missing_on_pack,
            hazard_type=rule.hazard_type or warning.hazard_type,
            actions=list(rule.actions),
        )

    def as_text(self, kind: str) -> str:
        """The policy excerpt the drafter sees, naming the concept each rule comes from."""
        most_severe_first = list(reversed(self.severity_order))
        if kind == "recall":
            severities = "; ".join(
                f"{sev}: {', '.join(hazards)}"
                for sev in most_severe_first
                if (
                    hazards := [
                        h for h, s in self.recall.severity_by_hazard.items() if s == sev
                    ]
                )
            )
            targets = "; ".join(
                f"{sev}: customers messaged within {t.customers_messaged} min, shelves clear within {t.shelves_clear} min"
                if t.customers_messaged or t.shelves_clear
                else f"{sev}: no time targets"
                for sev in most_severe_first
                if (t := self.recall.targets_minutes[sev])
            )
            reason = (
                "; dropping it needs a recorded reason"
                if self.recall.checkout_block_drop_needs_reason
                else ""
            )
            return (
                f"Recall response ({RECALL}). Severity follows the hazard type ({TAXONOMY}), not the notice "
                f"wording: {severities}. Time targets after approval: {targets}. A checkout block is requested "
                f"for {', '.join(self.recall.checkout_block_severities)} recalls{reason}. A store is exposed when "
                f"it holds the batch or received it within {self.recall.exposure_days} days; online orders within "
                f"{self.recall.order_lookback_days} days are messaged. Exposed stores get a pull for "
                f"{', '.join(self.recall.store_action_severities)} recalls; for any other severity they are "
                "listed as optional and the coordinator adds the ones to pull."
            )
        rules = "; ".join(
            f"{r.id} ({r.condition.rstrip('.')}): "
            f"{r.severity or 'severity by warning'}; "
            f"{', '.join(_ACTION_WORDS[a] for a in r.actions)}"
            for r in self.labels.rules
        )
        warnings = ", ".join(
            f"{w.value}: {w.severity_missing_on_pack}" for w in self.warnings.warnings
        )
        targets = "; ".join(
            f"{sev}: "
            + (
                ", ".join(
                    part
                    for part in (
                        f"holds verified within {t.holds_verified} min"
                        if t.holds_verified
                        else "",
                        f"listing fixed within {t.listing_fixed} min"
                        if t.listing_fixed
                        else "",
                    )
                    if part
                )
                or "no time targets"
            )
            for sev in most_severe_first
            if (t := self.labels.targets_minutes[sev])
        )
        return (
            f"Label rules ({LABELS}). Each finding's severity and actions come from its rule: {rules}. "
            f"Severity by warning, for a warning missing from the pack ({WARNING_HAZARDS}): {warnings}; any other "
            f"warning: {self.warnings.default.severity_missing_on_pack}. A hold covers every store holding the "
            f"lot. Time targets after approval: {targets}."
        )


def build(
    bundle: Bundle, now: datetime | None = None, require_usable: bool = True
) -> Policy:
    values = typed_values(bundle, POLICY_PATHS, now=now, require_usable=require_usable)
    return Policy(
        version=knowledge_version(bundle),
        taxonomy=values[TAXONOMY],
        recall=values[RECALL],
        labels=values[LABELS],
        warnings=values[WARNING_HAZARDS],
        match=values[MATCH],
        handling=values[HANDLING],
    )


def current(now: datetime | None = None) -> Policy:
    return build(load_bundle(), now=now)


def shelf_rule(now: datetime | None = None) -> ShelfCheckRule:
    """The shelf check's threshold, or PolicyUnavailable while the concept is unreviewed, invalid or stale."""
    return typed_values(load_bundle(), [TAXONOMY, SHELF], now=now)[SHELF]
