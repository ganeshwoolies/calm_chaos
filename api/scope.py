"""The scope job: takes every extracted notice to its match status, and raises a candidate for each exposed match.

For each pending notice whose extract has landed in psd.events:
- a failed extraction, or a date the lineage cannot read, is recorded as extraction_failed;
- a notice from a live feed (match: false in config/feeds.yaml) is not_in_range without being matched;
- otherwise sql/match_recalls.sql lists the catalogue products the notice may name, and decide() applies the match rule;
- a match runs attested recall lineage. Exposure raises a candidate; none records matched_no_exposure with the receipt.

Outcomes, matches and candidates are written in one transaction, and candidates are published only after it commits,
from the incident_candidates rows not yet published. A crash therefore repeats no outcome and loses no candidate, and a
candidate published twice is admitted once by the workflow.
"""

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from google.cloud import bigquery

from api import feeds
from api.publish import publish
from app import actions, attest, bq, evidence, policy
from app.knowledge import REPO_DIR, MatchRule, PolicyUnavailable
from app.schemas import Lineage, LineageRow

logger = logging.getLogger(__name__)

CANDIDATES_TOPIC = "psd-incident-candidates"
EMBED_SQL = REPO_DIR / "sql" / "embed_catalogue.sql"
MATCH_SQL = REPO_DIR / "sql" / "match_recalls.sql"
MATCHED_BY = "scope"

_LANDED_SQL = """SELECT n.guid, n.event_id, n.feed, e.recall_extract, e.tag_error
FROM recall_notices AS n
JOIN v_events_dedup AS e USING (event_id)
WHERE n.match_status = 'pending' AND e.source = 'recall'
ORDER BY n.first_seen"""

_INSERT_MATCHES = """INSERT INTO recall_matches (event_id, product_id, rank, method, distance, same_product, created_at)
SELECT event_id, product_id, rank, method, distance, same_product, CURRENT_TIMESTAMP() FROM UNNEST(@matches);
"""

# Only a notice still pending is updated, so an outcome written by a coordinator is never overwritten.
_MERGE_NOTICES = """MERGE recall_notices AS t
USING (SELECT * FROM UNNEST(@outcomes)) AS s
ON t.guid = s.guid AND t.match_status = 'pending'
WHEN MATCHED THEN UPDATE SET
  recall_extract = SAFE.PARSE_JSON(s.recall_extract), match_status = s.match_status, matched_product_id = s.matched_product_id,
  match_method = s.match_method, match_distance = s.match_distance, match_options = s.match_options,
  matched_by = s.matched_by, receipt_id = s.receipt_id, candidate_id = s.candidate_id,
  updated_at = CURRENT_TIMESTAMP();
"""

_MERGE_CANDIDATES = """MERGE incident_candidates AS t
USING (SELECT * FROM UNNEST(@candidates)) AS s
ON t.candidate_id = s.candidate_id
WHEN NOT MATCHED THEN INSERT
  (candidate_id, kind, product_id, guid, batch_ids, event_ids, stores, online_orders, receipt_ids, created_at, published)
  VALUES (s.candidate_id, s.kind, s.product_id, s.guid, s.batch_ids, s.event_ids, s.stores, s.online_orders,
    s.receipt_ids, CURRENT_TIMESTAMP(), FALSE);
"""

_UNPUBLISHED_SQL = """SELECT candidate_id, kind, event_ids FROM incident_candidates
WHERE NOT IFNULL(published, FALSE)
ORDER BY created_at"""

_MARK_PUBLISHED_SQL = """UPDATE incident_candidates SET published = TRUE, published_at = CURRENT_TIMESTAMP()
WHERE candidate_id IN UNNEST(@ids)"""

_lock = threading.Lock()


@dataclass(frozen=True)
class CatalogueMatch:
    """One catalogue product considered for a notice: a row of match_recalls.sql and of recall_matches."""

    product_id: str | None
    rank: int | None
    method: str
    distance: float | None
    same_product: bool | None


@dataclass(frozen=True)
class Decision:
    status: str
    product_id: str | None = None
    method: str | None = None
    distance: float | None = None
    options: tuple[str, ...] = ()


def decide(matches: list[CatalogueMatch], rule: MatchRule) -> Decision:
    """The match rule: a barcode we sell first, then the Gemini-confirmed embedding neighbours within max_distance."""
    if rule.barcode_first:
        barcode = sorted(
            {m.product_id for m in matches if m.method == "barcode" and m.product_id}
        )
        if len(barcode) == 1:
            return Decision("matched", product_id=barcode[0], method="barcode")
        if barcode:
            return Decision("ambiguous", options=tuple(barcode))
    confirmed = sorted(
        (
            m
            for m in matches
            if m.method == "embedding"
            and m.product_id
            and m.distance is not None
            and m.distance <= rule.max_distance
            and (m.same_product is True or not rule.require_model_confirmation)
        ),
        key=lambda m: m.distance or 0.0,
    )
    if not confirmed:
        return Decision("not_in_range")
    best = confirmed[0].distance or 0.0
    close = [m for m in confirmed if (m.distance or 0.0) - best < rule.ambiguity_gap]
    if len(close) > 1:
        return Decision(
            "ambiguous", options=tuple(m.product_id for m in close if m.product_id)
        )
    return Decision(
        "matched", product_id=confirmed[0].product_id, method="embedding", distance=best
    )


def candidate_id(guid: str, product_id: str) -> str:
    return f"recall:{hashlib.sha1(guid.encode('utf-8')).hexdigest()[:8]}:{product_id}"


def _bad_dates(extract: dict[str, Any]) -> list[str]:
    """Best-before dates lineage would read but that are not ISO dates."""
    bad = []
    for d in extract.get("date_codes") or []:
        if not isinstance(d, dict) or d.get("kind") != "best_before":
            continue
        for value in (d.get("from"), d.get("to")):
            if value is None:
                continue
            try:
                date.fromisoformat(str(value))
            except ValueError:
                bad.append(str(value))
    return bad


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: Any) -> list[str]:
    return [str(v).strip() for v in value if v] if isinstance(value, list) else []


def match_notices(
    extracts: dict[str, dict[str, Any]], rule: MatchRule
) -> dict[str, list[CatalogueMatch]]:
    """The catalogue products each extract (by event id) may name, after embedding any changed catalogue rows."""
    client = bq.client()
    client.query(
        EMBED_SQL.read_text(encoding="utf-8"),
        job_config=bq.job_config(),
        location=bq.location(),
    ).result()
    notices = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("event_id", "STRING", event_id),
            bigquery.ScalarQueryParameter("brand", "STRING", _text(x.get("brand"))),
            bigquery.ScalarQueryParameter(
                "product_name", "STRING", _text(x.get("product_name"))
            ),
            bigquery.ScalarQueryParameter(
                "sizes", "STRING", ", ".join(_texts(x.get("sizes")))
            ),
            bigquery.ArrayQueryParameter(
                "barcodes", "STRING", _texts(x.get("barcodes"))
            ),
        )
        for event_id, x in extracts.items()
    ]
    rows = bq.rows(
        MATCH_SQL.read_text(encoding="utf-8"),
        [
            bigquery.ArrayQueryParameter("notices", "STRUCT", notices),
            bigquery.ScalarQueryParameter("barcode_first", "BOOL", rule.barcode_first),
            bigquery.ScalarQueryParameter("top_k", "INT64", rule.top_k),
            bigquery.ScalarQueryParameter("max_distance", "FLOAT64", rule.max_distance),
        ],
    )
    found: dict[str, list[CatalogueMatch]] = {}
    for r in rows:
        found.setdefault(r["event_id"], []).append(
            CatalogueMatch(
                r["product_id"],
                r["rank"],
                r["method"],
                r["distance"],
                r["same_product"],
            )
        )
    return found


def _lineage(
    guid: str, extract: dict[str, Any], product_id: str, pol: policy.Policy
) -> Lineage:
    params = evidence.lineage_params(
        {"kind": "recall", "product_id": product_id, "notice": {"extract": extract}},
        pol,
    )
    as_of = datetime.now(UTC).replace(microsecond=0)
    receipt = attest.run_attested(
        evidence.LINEAGE,
        {
            **(params or {}),
            "as_of": as_of,
            "order_lookback_days": pol.recall.order_lookback_days,
        },
        used_by=f"scope:{guid}",
    )
    return Lineage(
        receipt_id=receipt.receipt_id,
        as_of=as_of.isoformat(),
        rows=[LineageRow.model_validate(r) for r in receipt.result],
    )


def _outcome(guid: str, extract: str, status: str, **fields: Any) -> dict[str, Any]:
    return {
        "guid": guid,
        "recall_extract": extract,
        "match_status": status,
        "matched_product_id": fields.get("product_id"),
        "match_method": fields.get("method"),
        "match_distance": fields.get("distance"),
        "match_options": list(fields.get("options") or []),
        "matched_by": MATCHED_BY if fields.get("product_id") else None,
        "receipt_id": fields.get("receipt_id"),
        "candidate_id": fields.get("candidate_id"),
    }


def _struct(fields: list[tuple[str, str, Any]]) -> bigquery.StructQueryParameter:
    params: list[Any] = []
    for name, kind, value in fields:
        if kind.startswith("ARRAY<"):
            params.append(bigquery.ArrayQueryParameter(name, kind[6:-1], value or []))
        else:
            params.append(bigquery.ScalarQueryParameter(name, kind, value))
    return bigquery.StructQueryParameter(None, *params)


def _write(outcomes: list[dict], matches: list[dict], candidates: list[dict]) -> None:
    statements: list[str] = []
    params: list[Any] = []
    if matches:
        statements.append(_INSERT_MATCHES)
        params.append(
            bigquery.ArrayQueryParameter(
                "matches",
                "STRUCT",
                [
                    _struct(
                        [
                            ("event_id", "STRING", m["event_id"]),
                            ("product_id", "STRING", m["product_id"]),
                            ("rank", "INT64", m["rank"]),
                            ("method", "STRING", m["method"]),
                            ("distance", "FLOAT64", m["distance"]),
                            ("same_product", "BOOL", m["same_product"]),
                        ]
                    )
                    for m in matches
                ],
            )
        )
    if outcomes:
        statements.append(_MERGE_NOTICES)
        params.append(
            bigquery.ArrayQueryParameter(
                "outcomes",
                "STRUCT",
                [
                    _struct(
                        [
                            ("guid", "STRING", o["guid"]),
                            ("recall_extract", "STRING", o["recall_extract"]),
                            ("match_status", "STRING", o["match_status"]),
                            ("matched_product_id", "STRING", o["matched_product_id"]),
                            ("match_method", "STRING", o["match_method"]),
                            ("match_distance", "FLOAT64", o["match_distance"]),
                            ("match_options", "ARRAY<STRING>", o["match_options"]),
                            ("matched_by", "STRING", o["matched_by"]),
                            ("receipt_id", "STRING", o["receipt_id"]),
                            ("candidate_id", "STRING", o["candidate_id"]),
                        ]
                    )
                    for o in outcomes
                ],
            )
        )
    if candidates:
        statements.append(_MERGE_CANDIDATES)
        params.append(
            bigquery.ArrayQueryParameter(
                "candidates",
                "STRUCT",
                [
                    _struct(
                        [
                            ("candidate_id", "STRING", c["candidate_id"]),
                            ("kind", "STRING", c["kind"]),
                            ("product_id", "STRING", c["product_id"]),
                            ("guid", "STRING", c["guid"]),
                            ("batch_ids", "ARRAY<STRING>", c["batch_ids"]),
                            ("event_ids", "ARRAY<STRING>", c["event_ids"]),
                            ("stores", "ARRAY<STRING>", c["stores"]),
                            ("online_orders", "INT64", c["online_orders"]),
                            ("receipt_ids", "ARRAY<STRING>", c["receipt_ids"]),
                        ]
                    )
                    for c in candidates
                ],
            )
        )
    if not statements:
        return
    script = "BEGIN TRANSACTION;\n" + "".join(statements) + "COMMIT TRANSACTION;"
    bq.client().query(
        script, job_config=bq.job_config(params), location=bq.location()
    ).result()


def _publish_candidates() -> list[str]:
    published = []
    for c in bq.rows(_UNPUBLISHED_SQL):
        event_id = (c["event_ids"] or [c["candidate_id"]])[0]
        body = {"candidate_id": c["candidate_id"], "kind": c["kind"]}
        if publish(
            CANDIDATES_TOPIC, body, event_id, c["kind"], candidate_id=c["candidate_id"]
        ):
            published.append(c["candidate_id"])
    if published:
        bq.rows(
            _MARK_PUBLISHED_SQL,
            [bigquery.ArrayQueryParameter("ids", "STRING", published)],
        )
    return published


def _run() -> dict[str, Any]:
    pol = policy.current()
    matched_feeds = feeds.matched_feeds()
    landed = bq.rows(_LANDED_SQL)
    outcomes: list[dict] = []
    matches: list[dict] = []
    candidates: list[dict] = []
    readable: list[tuple[dict, dict]] = []
    for n in landed:
        try:
            extract = json.loads(n["recall_extract"] or "{}")
        except ValueError:
            extract = {}
        if n["tag_error"] or not isinstance(extract, dict):
            outcomes.append(
                _outcome(n["guid"], n["recall_extract"] or "{}", "extraction_failed")
            )
        elif n["feed"] not in matched_feeds:
            # A real notice names a real brand: by rule, never by the model's judgement, it is not in the catalogue.
            outcomes.append(_outcome(n["guid"], n["recall_extract"], "not_in_range"))
        elif bad := _bad_dates(extract):
            logger.warning(
                "notice %s: best-before dates lineage cannot read: %s", n["guid"], bad
            )
            outcomes.append(
                _outcome(n["guid"], n["recall_extract"], "extraction_failed")
            )
        else:
            readable.append((n, extract))

    found = (
        match_notices({n["event_id"]: x for n, x in readable}, pol.match)
        if readable
        else {}
    )
    for n, extract in readable:
        considered = found.get(n["event_id"], [])
        if any(m.method == "embedding_failed" for m in considered):
            logger.warning("notice %s: embedding failed; it stays pending", n["guid"])
            continue
        d = decide(considered, pol.match)
        fields: dict[str, Any] = {
            "product_id": d.product_id,
            "method": d.method,
            "distance": d.distance,
            "options": d.options,
        }
        status = d.status
        if status == "matched" and d.product_id:
            try:
                lineage = _lineage(n["guid"], extract, d.product_id, pol)
            except (attest.AttestationFailed, PolicyUnavailable, ValueError) as e:
                logger.error(
                    "notice %s: lineage failed, it stays pending: %s", n["guid"], e
                )
                continue
            fields["receipt_id"] = lineage.receipt_id
            exposed = actions.exposed_stores(lineage, pol)
            if exposed or lineage.order_ids:
                cid = candidate_id(n["guid"], d.product_id)
                fields["candidate_id"] = cid
                candidates.append(
                    {
                        "candidate_id": cid,
                        "kind": "recall",
                        "product_id": d.product_id,
                        "guid": n["guid"],
                        "batch_ids": sorted({r.batch_id for r in lineage.rows}),
                        "event_ids": [n["event_id"]],
                        "stores": sorted({r.store_id for r in exposed}),
                        "online_orders": len(lineage.order_ids),
                        "receipt_ids": [lineage.receipt_id],
                    }
                )
            else:
                status = "matched_no_exposure"
        outcomes.append(_outcome(n["guid"], n["recall_extract"], status, **fields))
        matches.extend(
            {
                "event_id": n["event_id"],
                "product_id": m.product_id,
                "rank": m.rank,
                "method": m.method,
                "distance": m.distance,
                "same_product": m.same_product,
            }
            for m in considered
        )
    _write(outcomes, matches, candidates)
    published = _publish_candidates()
    summary: dict[str, int] = {}
    for o in outcomes:
        summary[o["match_status"]] = summary.get(o["match_status"], 0) + 1
    logger.info(
        "scope: %d landed, outcomes %s, %d candidates published",
        len(landed),
        summary,
        len(published),
    )
    return {
        "landed": len(landed),
        "outcomes": summary,
        "candidates": [c["candidate_id"] for c in candidates],
        "published": published,
    }


def run() -> dict[str, Any]:
    """One scope pass; skipped while another is running."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "running"}
    try:
        return _run()
    finally:
        _lock.release()
