"""Creates the desk's BigQuery tables and views, and loads the synthetic world into them.

    uv run python data/load_truth.py --dataset psd [--anchor <ISO 8601 instant>] [--ddl-only] [--dry-run]

Tables are created from sql/ddl when missing and views from sql/views. Only the generated world tables are replaced,
in full and timed from the anchor (the load time unless given), so a reload resets the world. Pipeline tables
(events, notices, matches, candidates, embeddings) and attestations are created but never cleared: they are history.
"""

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery

from app import bq
from data.gen_catalogue import build_catalogue, load_truth
from data.gen_supply import build_supply

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
DDL_DIR = SQL_DIR / "ddl"
VIEW_DIR = SQL_DIR / "views"
_CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)")
_VIEW = re.compile(r"CREATE OR REPLACE VIEW (\w+)")

# Columns the DDL no longer has. ALTER ... IF EXISTS keeps a re-run harmless.
DROPPED_COLUMNS = {"products": ["embedding"]}


def apply_ddl(client: bigquery.Client, dataset: str) -> list[str]:
    """Creates missing tables, then views, qualifying names by project and dataset so the files name neither."""
    created = []
    qualified = f"{client.project}.{dataset}"
    for path in sorted(DDL_DIR.glob("*.sql")):
        ddl = _CREATE.sub(
            lambda m: f"CREATE TABLE IF NOT EXISTS `{qualified}.{m.group(1)}`",
            path.read_text(encoding="utf-8"),
            count=1,
        )
        client.query(ddl, location=bq.location()).result()
        created.append(path.stem)
    for table, columns in DROPPED_COLUMNS.items():
        for column in columns:
            client.query(
                f"ALTER TABLE `{qualified}.{table}` DROP COLUMN IF EXISTS {column}",
                location=bq.location(),
            ).result()
    for path in sorted(VIEW_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8").replace("__DATASET__", qualified)
        sql = _VIEW.sub(
            lambda m: f"CREATE OR REPLACE VIEW `{qualified}.{m.group(1)}`", sql, count=1
        )
        client.query(sql, location=bq.location()).result()
        created.append(path.stem)
    return created


def load_table(
    client: bigquery.Client, dataset: str, name: str, rows: list[dict]
) -> int:
    table = client.get_table(f"{client.project}.{dataset}.{name}")
    config = bigquery.LoadJobConfig(
        schema=table.schema,
        time_partitioning=table.time_partitioning,
        clustering_fields=table.clustering_fields,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    client.load_table_from_json(
        rows, table, job_config=config, location=bq.location()
    ).result()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default=bq.dataset())
    parser.add_argument(
        "--anchor", help="ISO 8601 instant the world is timed from; default now"
    )
    parser.add_argument(
        "--ddl-only",
        action="store_true",
        help="create missing tables and views; load no data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate and count rows; touch nothing in BigQuery",
    )
    args = parser.parse_args()

    anchor = (
        datetime.fromisoformat(args.anchor)
        if args.anchor
        else datetime.now(UTC).replace(second=0, microsecond=0)
    )
    tables: dict[str, list[dict]] = {}
    if not args.ddl_only:
        truth = load_truth()
        catalogue = build_catalogue(truth, anchor)
        supply = build_supply(truth, catalogue, anchor)
        tables = {
            "products": catalogue.products,
            "suppliers": catalogue.suppliers,
            "supplier_specs": catalogue.specs,
            **supply.tables(),
        }
    if args.dry_run:
        for name, rows in tables.items():
            print(f"{name}: {len(rows)} rows")
        return 0

    client = bq.client()
    print(
        f"tables and views in {client.project}.{args.dataset}: {', '.join(apply_ddl(client, args.dataset))}"
    )
    for name, rows in tables.items():
        print(f"loaded {name}: {load_table(client, args.dataset, name, rows)} rows")
    if tables:
        print(f"world timed from {anchor.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
