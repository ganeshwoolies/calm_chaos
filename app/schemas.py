"""Data shapes that flow between the incident workflow's nodes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Kind = Literal["recall", "label"]
Severity = Literal["critical", "high", "medium", "low"]


class Candidate(BaseModel):
    candidate_id: str
    kind: Kind


class LineageRow(BaseModel):
    """One row of the recall-lineage computation: a store holding a batch, or an online order containing it."""

    row_kind: Literal["store", "order"]
    batch_id: str
    code: str
    store_id: str
    delivered: int | None = None
    on_hand: int | None = None
    aisle: str | None = None
    last_delivered: str | None = None
    order_id: str | None = None


class Lineage(BaseModel):
    receipt_id: str
    as_of: str
    rows: list[LineageRow] = []

    @property
    def store_rows(self) -> list[LineageRow]:
        return [r for r in self.rows if r.row_kind == "store"]

    @property
    def order_ids(self) -> list[str]:
        return sorted(
            {r.order_id for r in self.rows if r.row_kind == "order" and r.order_id}
        )


class Product(BaseModel):
    product_id: str
    name: str
    brand: str
    size: str
    category: str
    supplier_id: str
    supplier_name: str


class NoticeExtract(BaseModel):
    product_name: str | None = None
    brand: str | None = None
    sizes: list[str] = []
    batch_codes: list[str] = []
    date_codes: list[dict] = []
    hazard_type: str | None = None
    hazard_detail: str | None = None
    consumer_action: str | None = None
    summary: str | None = None


class Notice(BaseModel):
    guid: str
    feed: str
    title: str
    url: str
    published_at: str
    extract: NoticeExtract
    attribution: str | None = Field(
        default=None, description="The source to credit wherever the notice is shown"
    )


class Match(BaseModel):
    method: Literal["barcode", "embedding", "coordinator"]
    distance: float | None = None
    confirmed: bool


class LabelFinding(BaseModel):
    rule: str
    field: str
    value: str
    severity: Severity
    actions: list[str]
    hazard_type: str


class LabelCheck(BaseModel):
    check_id: str
    store_id: str
    checked_at: str
    photo_uri: str
    lot: str | None = None
    findings: list[LabelFinding]


class EvidencePack(BaseModel):
    candidate_id: str
    kind: Kind
    product: Product
    hazard_type: str
    title_hint: str
    notice: Notice | None = None
    match: Match | None = None
    checks: list[LabelCheck] = []
    lineage: Lineage | None = None
    prior_incidents: list[str] = []

    @property
    def receipts(self) -> list[str]:
        return [self.lineage.receipt_id] if self.lineage else []


class StoreAction(BaseModel):
    store_id: str
    batch_id: str
    code: str
    action: Literal["hold", "pull"]
    qty_on_hand: int
    aisle: str | None = None


class ListingFix(BaseModel):
    field: Literal["allergens", "warnings", "marks", "origin"]
    add: list[str] = []
    remove: list[str] = []
    set_to: str | None = None


class Targets(BaseModel):
    message_minutes: int | None = None
    shelf_minutes: int | None = None
    listing_minutes: int | None = None


class ProposedActions(BaseModel):
    """Computed by code from policy and evidence. The coordinator may edit it; the model may not."""

    kind: Kind
    severity: Severity
    targets: Targets
    store_actions: list[StoreAction] = []
    optional_store_actions: list[StoreAction] = Field(
        default=[],
        description="Exposed stores the policy proposes no action for; the coordinator may add them",
    )
    checkout_block: bool = False
    message_orders: list[str] = []
    listing_fixes: list[ListingFix] = []
    supplier_notice: bool = False
    vendor_case: bool = False
    considerations: list[str] = []
    receipts: list[str] = []


class CustomerMessage(BaseModel):
    subject: str
    body: str = Field(
        description="Product, batch or best-before, the hazard, what to do and the refund, in plain words. "
        "No order numbers, names or dates of purchase: code adds those per order."
    )


class IncidentText(BaseModel):
    """Written by the drafter."""

    title: str = Field(
        description="Product, batch or lot, hazard, and scale in one line"
    )
    narrative: str = Field(
        description="Three to five sentences the coordinator reads first"
    )
    evidence: list[str] = Field(
        description="Notice lines, the match, figures with their receipt ids, label findings"
    )
    considerations: list[str] = Field(
        description="What the coordinator should weigh before approving"
    )
    customer_message: CustomerMessage | None = Field(
        default=None, description="Only when the proposed actions message online orders"
    )
    supplier_notice: str | None = Field(
        default=None, description="Only when the proposed actions include one"
    )
    vendor_case_body: str = Field(
        description="Facts only: product, batch or lot, hazard, stores, dates"
    )
    qa_alert: str = Field(description="One paragraph for the QA team")
    sources_used: list[str] = Field(
        default=[],
        description="Paths from the policy and verified knowledge blocks the text relied on",
    )


class TextOverrides(BaseModel):
    title: str | None = None
    narrative: str | None = None
    customer_message_subject: str | None = None
    customer_message_body: str | None = None
    supplier_notice: str | None = None
    vendor_case_body: str | None = None
    qa_alert: str | None = None


class Decision(BaseModel):
    """The coordinator's reply at the approval pause."""

    decision: Literal["approve", "dismiss"]
    actor: str = "coordinator"
    reason: str | None = None
    remove_stores: list[str] = []
    pull_stores: list[str] = Field(
        default=[], description="Stores whose proposed hold becomes a pull"
    )
    add_stores: list[str] = Field(
        default=[],
        description="Stores from the optional store actions to add as tasks",
    )
    checkout_block: bool | None = None
    text: TextOverrides = TextOverrides()

    @model_validator(mode="after")
    def _dismissal_has_a_reason(self) -> "Decision":
        # The incident handling policy: a dismissal records a reason. The desk page asks for one; this enforces it.
        if self.decision == "dismiss" and not (self.reason or "").strip():
            raise ValueError("a dismissal needs a reason")
        return self


class ShelfCheck(BaseModel):
    """What Gemini sees in a shelf photo. The verdict is code's, by /policy/shelf-check.md."""

    target_present: bool = Field(
        description="Whether any unit of the named product is still visible on the shelf"
    )
    confidence: float = Field(
        ge=0, le=1, description="How sure the reading is, from 0 to 1"
    )
    what_was_seen: list[str] = Field(
        default=[], description="The products whose names can be read on the shelf"
    )
    codes_seen: list[str] = Field(
        default=[], description="Batch or lot codes legible in the photo, if any"
    )
    reason: str = Field(description="One sentence on what decided the reading")
    retake: bool = Field(
        description="True when blur, glare, angle or the wrong shelf makes the photo unusable"
    )


class ShelfVerdict(BaseModel):
    """The store's reply at a verification pause: the verdict, with the shelf photo and its reading when one was taken."""

    verdict: Literal["verified_clear", "not_clear", "retake"]
    note: str | None = None
    photo_uri: str | None = None
    check: ShelfCheck | None = None


class Promotion(BaseModel):
    """A coordinator's verification of one observation, which promotes it into the knowledge bundle."""

    actor: str
    stale_after: datetime = Field(
        description="When the note goes stale unless verified again; an instant with a UTC offset"
    )
    text: str | None = Field(
        default=None,
        description="The coordinator's wording; the observation's own when absent",
    )


class DeployedCommit(BaseModel):
    deployed_sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")
