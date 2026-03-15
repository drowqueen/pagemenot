"""Tests for _alarm_incidents tracking and SNS OK recovery path."""

from unittest.mock import AsyncMock, patch

import pytest

import pagemenot.main as main_mod
from pagemenot.triage import _active_incidents, _dedup_key, _dedup_lock


@pytest.fixture(autouse=True)
def reset_tracking():
    main_mod._alarm_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()
    yield
    main_mod._alarm_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()


# ── _alarm_incidents state ─────────────────────────────────────────────────


class TestAlarmIncidents:
    def test_empty_initially(self):
        assert len(main_mod._alarm_incidents) == 0

    def test_entry_stored_and_retrieved(self):
        main_mod._alarm_incidents["EC2-Nginx-Health"] = {
            "jira_url": "https://jira.example/browse/INC-42",
            "pd_url": "https://pd.example/incidents/P1",
            "channel": "alerts",
            "thread_ts": "123.456",
        }
        entry = main_mod._alarm_incidents["EC2-Nginx-Health"]
        assert entry["jira_url"] == "https://jira.example/browse/INC-42"
        assert entry["pd_url"] == "https://pd.example/incidents/P1"

    def test_pop_removes_entry(self):
        main_mod._alarm_incidents["alarm-1"] = {
            "jira_url": "x",
            "pd_url": "y",
            "channel": "c",
            "thread_ts": "t",
        }
        entry = main_mod._alarm_incidents.pop("alarm-1", None)
        assert entry is not None
        assert "alarm-1" not in main_mod._alarm_incidents

    def test_pop_missing_key_returns_none(self):
        assert main_mod._alarm_incidents.pop("nonexistent", None) is None

    def test_multiple_alarms_tracked_independently(self):
        main_mod._alarm_incidents["alarm-a"] = {
            "jira_url": "INC-1",
            "pd_url": "",
            "channel": "c",
            "thread_ts": "t",
        }
        main_mod._alarm_incidents["alarm-b"] = {
            "jira_url": "INC-2",
            "pd_url": "",
            "channel": "c",
            "thread_ts": "t",
        }
        assert main_mod._alarm_incidents["alarm-a"]["jira_url"] == "INC-1"
        assert main_mod._alarm_incidents["alarm-b"]["jira_url"] == "INC-2"

    def test_dedup_key_stable_across_fire_and_resolve(self):
        from pagemenot.triage import _parse_alert

        fire = _parse_alert(
            "alertmanager",
            {
                "status": "firing",
                "labels": {"alertname": "OOMKilled", "service": "checkout", "severity": "critical"},
                "annotations": {},
            },
        )
        resolve = _parse_alert(
            "alertmanager",
            {
                "status": "resolved",
                "labels": {"alertname": "OOMKilled", "service": "checkout", "severity": "critical"},
                "annotations": {},
            },
        )
        assert _dedup_key(fire["service"], fire["title"]) == _dedup_key(
            resolve["service"], resolve["title"]
        )


# ── SNS OK recovery path ───────────────────────────────────────────────────


SNS_ALARM_PAYLOAD = {
    "Type": "Notification",
    "Message": '{"AlarmName":"EC2-Nginx-Health","NewStateValue":"ALARM","NewStateReason":"threshold","OldStateValue":"OK","Trigger":{"MetricName":"HealthCheck"}}',
    "Subject": "ALARM: EC2-Nginx-Health",
    "TopicArn": "arn:aws:sns:eu-west-1:123456789:pagemenot-alerts",
}

SNS_OK_PAYLOAD = {
    "Type": "Notification",
    "Message": '{"AlarmName":"EC2-Nginx-Health","NewStateValue":"OK","NewStateReason":"back to normal","OldStateValue":"ALARM","Trigger":{"MetricName":"HealthCheck"}}',
    "Subject": "OK: EC2-Nginx-Health",
    "TopicArn": "arn:aws:sns:eu-west-1:123456789:pagemenot-alerts",
}


@pytest.mark.asyncio
async def test_sns_ok_clears_alarm_incidents():
    from httpx import ASGITransport, AsyncClient
    from pagemenot.main import app

    main_mod._alarm_incidents["EC2-Nginx-Health"] = {
        "jira_url": "https://jira.example/browse/INC-99",
        "pd_url": "",
        "channel": "alerts",
        "thread_ts": "123.456",
    }

    with (
        patch("pagemenot.main._resolve_jira_ticket", new_callable=AsyncMock),
        patch("pagemenot.main._resolve_pagerduty_incident", new_callable=AsyncMock),
        patch("pagemenot.slack_bot.get_client") as mock_gc,
        patch("pagemenot.main._verif_store") as mock_store,
    ):
        mock_store.pop = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.chat_postMessage = AsyncMock(return_value={"ts": "456.789"})
        mock_gc.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/webhooks/sns", json=SNS_OK_PAYLOAD)

    assert resp.status_code == 200
    assert "EC2-Nginx-Health" not in main_mod._alarm_incidents


@pytest.mark.asyncio
async def test_sns_ok_with_no_tracked_incident_does_not_raise():
    from httpx import ASGITransport, AsyncClient
    from pagemenot.main import app

    with (
        patch("pagemenot.main._resolve_jira_ticket", new_callable=AsyncMock),
        patch("pagemenot.main._resolve_pagerduty_incident", new_callable=AsyncMock),
        patch("pagemenot.slack_bot.get_client") as mock_gc,
        patch("pagemenot.main._verif_store") as mock_store,
    ):
        mock_store.pop = AsyncMock(return_value=None)
        mock_gc.return_value = AsyncMock()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/webhooks/sns", json=SNS_OK_PAYLOAD)

    assert resp.status_code == 200
