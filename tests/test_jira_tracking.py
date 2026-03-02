"""Integration tests for Jira/PD incident tracking and resolve handling.

External services (Slack client, _close_jira_ticket) are mocked at the
call boundary. Module-level state is reset between tests via fixture.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import pagemenot.main as main_mod
from pagemenot.triage import _active_incidents, _dedup_key, _dedup_lock


@pytest.fixture(autouse=True)
def reset_tracking():
    """Reset all in-memory incident tracking state before each test."""
    main_mod._active_jira_tickets.clear()
    main_mod._active_pd_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()
    yield
    main_mod._active_jira_tickets.clear()
    main_mod._active_pd_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()


@pytest.fixture
def mock_slack_client():
    mock = AsyncMock()
    mock.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
    with patch("pagemenot.slack_bot.get_client", return_value=mock):
        yield mock


def am_resolve(alertname="OOMKilled", service="checkout"):
    return {
        "status": "resolved",
        "labels": {"alertname": alertname, "service": service, "severity": "critical"},
        "annotations": {},
    }


# ── Jira dedup state ──────────────────────────────────────────────────────

class TestJiraTracking:
    def test_no_ticket_tracked_initially(self):
        key = _dedup_key("checkout", "OOMKilled")
        assert main_mod._active_jira_tickets.get(key) is None

    def test_ticket_stored_and_retrieved(self):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-42"
        assert main_mod._active_jira_tickets[key] == "INC-42"

    def test_different_alerts_tracked_independently(self):
        k1 = _dedup_key("checkout", "OOMKilled")
        k2 = _dedup_key("payment", "HighLatency")
        main_mod._active_jira_tickets[k1] = "INC-1"
        main_mod._active_jira_tickets[k2] = "INC-2"
        assert main_mod._active_jira_tickets[k1] == "INC-1"
        assert main_mod._active_jira_tickets[k2] == "INC-2"

    def test_dedup_key_stable_across_fire_and_resolve(self):
        from pagemenot.triage import _parse_alert
        fire = _parse_alert("alertmanager", {
            "status": "firing",
            "labels": {"alertname": "OOMKilled", "service": "checkout", "severity": "critical"},
            "annotations": {},
        })
        resolve = _parse_alert("alertmanager", {
            "status": "resolved",
            "labels": {"alertname": "OOMKilled", "service": "checkout", "severity": "critical"},
            "annotations": {},
        })
        assert _dedup_key(fire["service"], fire["title"]) == _dedup_key(resolve["service"], resolve["title"])


# ── _handle_resolve ────────────────────────────────────────────────────────

class TestHandleResolve:
    async def test_no_jira_tracked_skips_close(self, mock_slack_client):
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock) as mock_close:
            await main_mod._handle_resolve("alertmanager", am_resolve())
            mock_close.assert_not_called()

    async def test_tracked_jira_is_closed(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-99"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True) as mock_close:
            await main_mod._handle_resolve("alertmanager", am_resolve())
            mock_close.assert_called_once()
            assert mock_close.call_args[0][0] == "INC-99"

    async def test_ticket_removed_from_tracking_on_success(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-99"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True):
            await main_mod._handle_resolve("alertmanager", am_resolve())
        assert key not in main_mod._active_jira_tickets

    async def test_ticket_kept_in_tracking_on_close_failure(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-99"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=False):
            await main_mod._handle_resolve("alertmanager", am_resolve())
        assert main_mod._active_jira_tickets.get(key) == "INC-99"

    async def test_dedup_registry_cleared_on_resolve(self, mock_slack_client):
        from pagemenot.triage import _check_and_register
        _check_and_register("checkout", "OOMKilled", "critical")
        key = _dedup_key("checkout", "OOMKilled")
        with _dedup_lock:
            assert key in _active_incidents

        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True):
            await main_mod._handle_resolve("alertmanager", am_resolve())

        with _dedup_lock:
            assert key not in _active_incidents

    async def test_pd_tracking_cleared_on_resolve(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_pd_incidents[key] = "https://pd.example/i/123"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True):
            await main_mod._handle_resolve("alertmanager", am_resolve())
        assert key not in main_mod._active_pd_incidents

    async def test_slack_notified_on_success(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-99"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True):
            await main_mod._handle_resolve("alertmanager", am_resolve())
        mock_slack_client.chat_postMessage.assert_called_once()
        call_text = mock_slack_client.chat_postMessage.call_args[1]["text"]
        assert "INC-99" in call_text
        assert "closed" in call_text.lower()

    async def test_slack_notified_on_close_failure(self, mock_slack_client):
        key = _dedup_key("checkout", "OOMKilled")
        main_mod._active_jira_tickets[key] = "INC-99"
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=False):
            await main_mod._handle_resolve("alertmanager", am_resolve())
        call_text = mock_slack_client.chat_postMessage.call_args[1]["text"]
        assert "could not close" in call_text.lower()

    async def test_malformed_payload_does_not_raise(self, mock_slack_client):
        # Should not raise — bad payloads are logged and dropped
        await main_mod._handle_resolve("alertmanager", {"garbage": True})
