"""desk_records: the rows sent to BigQuery, and a failed append that leaves the desk running."""

import json

from app import records


class FakeBigQuery:
    project = "p"

    def __init__(self, fail: Exception | None = None, errors: list | None = None):
        self.sent: list = []
        self.fail, self.errors = fail, errors or []

    def insert_rows_json(self, table, rows):
        if self.fail:
            raise self.fail
        self.sent.append((table, rows))
        return self.errors


def test_each_version_is_one_row_with_the_whole_record(monkeypatch) -> None:
    fake = FakeBigQuery()
    monkeypatch.setattr(records.bq, "client", lambda: fake)
    monkeypatch.setenv("PSD_DATASET", "psd")
    records.append(
        [
            ("incidents", "inc-1", {"status": "verifying", "approved_at": "t"}),
            ("tasks", "task-1", {"status": "open"}),
        ]
    )
    ((table, rows),) = fake.sent
    assert table == "p.psd.desk_records"
    assert [(r["collection"], r["record_id"]) for r in rows] == [
        ("incidents", "inc-1"),
        ("tasks", "task-1"),
    ]
    assert rows[0]["written_at"] == rows[1]["written_at"]
    assert json.loads(rows[0]["record"]) == {"status": "verifying", "approved_at": "t"}


def test_a_failed_append_is_logged_and_the_desk_goes_on(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        records.bq, "client", lambda: FakeBigQuery(fail=RuntimeError("no network"))
    )
    records.append([("incidents", "inc-1", {})])
    assert "not appended" in caplog.text
    monkeypatch.setattr(
        records.bq, "client", lambda: FakeBigQuery(errors=[{"index": 0}])
    )
    records.append([("incidents", "inc-1", {})])
    assert caplog.text.count("not appended") == 2


def test_nothing_is_sent_for_no_rows(monkeypatch) -> None:
    fake = FakeBigQuery()
    monkeypatch.setattr(records.bq, "client", lambda: fake)
    records.append([])
    assert fake.sent == []
