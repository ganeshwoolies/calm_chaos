from app import analytics, bq
from tools import ops_report


def test_the_plugin_is_off_without_a_dataset(monkeypatch) -> None:
    monkeypatch.delenv("PSD_ANALYTICS_DATASET", raising=False)
    assert analytics.plugins() == []


def test_the_plugin_writes_to_the_dataset_in_the_desk_region(monkeypatch) -> None:
    monkeypatch.setenv("PSD_ANALYTICS_DATASET", "psd_analytics")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "calm-chaos")
    (plugin,) = analytics.plugins()
    assert plugin.dataset_id == "psd_analytics" and plugin.project_id == "calm-chaos"
    assert plugin.config.table_id == "agent_events" and plugin.config.flush_on_run_end
    assert "HITL_CREDENTIAL_REQUEST" in plugin.config.event_denylist


def _rows(draft: dict, retrieval: dict):
    def rows(sql, parameters=()):
        assert "calm-chaos.psd_analytics.agent_events" in sql
        return [draft] if "drafts" in sql else [retrieval]

    return rows


def test_the_report_checks_both_targets(monkeypatch) -> None:
    monkeypatch.setenv("PSD_ANALYTICS_DATASET", "psd_analytics")
    monkeypatch.setattr(
        bq, "client", lambda: type("C", (), {"project": "calm-chaos"})()
    )
    monkeypatch.setattr(
        bq,
        "rows",
        _rows(
            {"drafts": 40, "p50_ms": 8000.0, "p95_ms": 18000.0},
            {"retrievals": 40, "timeouts": 0},
        ),
    )
    lines, ok = ops_report.report()
    assert ok and "p95 18.0 s" in lines[0] and "0 of 40" in lines[1]

    monkeypatch.setattr(
        bq,
        "rows",
        _rows(
            {"drafts": 40, "p50_ms": 9000.0, "p95_ms": 26000.0},
            {"retrievals": 50, "timeouts": 2},
        ),
    )
    lines, ok = ops_report.report()
    assert not ok and lines[0].endswith("MISSED") and lines[1].endswith("MISSED")


def test_the_report_needs_the_dataset(monkeypatch) -> None:
    monkeypatch.delenv("PSD_ANALYTICS_DATASET", raising=False)
    lines, ok = ops_report.report()
    assert not ok and "PSD_ANALYTICS_DATASET" in lines[0]
