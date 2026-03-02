"""Unit tests for pagemenot.triage — pure functions only."""
import hashlib
import time

import pytest

from pagemenot.triage import (
    TriageResult,
    _active_incidents,
    _check_and_register,
    _dedup_key,
    _dedup_lock,
    _parse_alert,
    _parse_crew_output,
)


@pytest.fixture(autouse=True)
def clear_dedup():
    with _dedup_lock:
        _active_incidents.clear()
    yield
    with _dedup_lock:
        _active_incidents.clear()


# ── _dedup_key ─────────────────────────────────────────────────────────────

class TestDedupKey:
    def test_deterministic(self):
        assert _dedup_key("checkout", "OOMKilled") == _dedup_key("checkout", "OOMKilled")

    def test_uses_sha256(self):
        _, h = _dedup_key("svc", "OOMKilled pods")
        assert h == hashlib.sha256("oomkilled pods".encode()).hexdigest()[:16]

    def test_case_insensitive(self):
        assert _dedup_key("CHECKOUT", "OOMKilled") == _dedup_key("checkout", "oomkilled")

    def test_different_services_differ(self):
        assert _dedup_key("checkout", "crash") != _dedup_key("payment", "crash")

    def test_different_titles_differ(self):
        assert _dedup_key("svc", "OOMKilled") != _dedup_key("svc", "HighLatency")

    def test_returns_two_strings(self):
        key = _dedup_key("svc", "alert")
        assert isinstance(key, tuple) and len(key) == 2
        assert all(isinstance(p, str) for p in key)


# ── _check_and_register ────────────────────────────────────────────────────

class TestCheckAndRegister:
    def test_first_call_not_duplicate(self):
        assert _check_and_register("svc", "OOMKilled", "critical") is False

    def test_second_call_within_ttl_is_duplicate(self):
        _check_and_register("svc", "OOMKilled", "critical")
        assert _check_and_register("svc", "OOMKilled", "critical") is True

    def test_different_service_not_duplicate(self):
        _check_and_register("svc-a", "OOMKilled", "critical")
        assert _check_and_register("svc-b", "OOMKilled", "critical") is False

    def test_different_title_not_duplicate(self):
        _check_and_register("svc", "OOMKilled", "critical")
        assert _check_and_register("svc", "HighLatency", "critical") is False

    def test_expired_entry_not_duplicate(self, monkeypatch):
        _check_and_register("svc", "OOMKilled", "critical")
        real = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real() + 99999)
        assert _check_and_register("svc", "OOMKilled", "critical") is False


# ── _parse_alert ───────────────────────────────────────────────────────────

class TestParseAlert:
    def _am(self, status="firing", alertname="OOMKilled", service="checkout", severity="critical"):
        return {
            "status": status,
            "labels": {"alertname": alertname, "service": service, "severity": severity},
            "annotations": {"description": f"{alertname} on {service}"},
        }

    def test_alertmanager_title_and_service(self):
        p = _parse_alert("alertmanager", self._am())
        assert p["title"] == "OOMKilled"
        assert p["service"] == "checkout"
        assert p["severity"] == "critical"

    def test_alertmanager_resolved_same_key_as_firing(self):
        fire = _parse_alert("alertmanager", self._am(status="firing"))
        resolve = _parse_alert("alertmanager", self._am(status="resolved"))
        assert _dedup_key(fire["service"], fire["title"]) == _dedup_key(resolve["service"], resolve["title"])

    def test_pagerduty_returns_required_fields(self):
        p = _parse_alert("pagerduty", {
            "title": "High error rate on payment-service",
            "service": {"name": "payment-service"},
            "urgency": "high",
        })
        assert p["title"]
        assert p["severity"] in ("critical", "high", "medium", "low", "unknown")

    def test_grafana_returns_required_fields(self):
        p = _parse_alert("grafana", {
            "status": "firing",
            "title": "High latency",
            "ruleName": "HighLatency",
        })
        assert p["title"]
        assert p["severity"] in ("critical", "high", "medium", "low", "unknown")

    def test_unknown_source_does_not_raise(self):
        p = _parse_alert("unknown_source", {"title": "x", "service": "y"})
        assert isinstance(p, dict)
        assert "title" in p


# ── _parse_crew_output ────────────────────────────────────────────────────

class TestParseCrewOutput:
    def _alert(self):
        return {"title": "OOMKilled", "service": "checkout", "severity": "critical"}

    def test_structured_populates_fields(self):
        structured = {
            "root_cause": "Memory leak in request handler",
            "confidence": "high",
            "evidence": ["Pod logs show OOM"],
            "remediation_steps": ["[AUTO-SAFE] kubectl rollout restart deployment/checkout"],
            "postmortem_summary": "OOM due to leak.",
        }
        r = _parse_crew_output("", structured, self._alert())
        assert r.root_cause == "Memory leak in request handler"
        assert r.confidence == "high"
        assert r.remediation_steps == ["[AUTO-SAFE] kubectl rollout restart deployment/checkout"]
        assert r.needs_approval == []

    def test_needs_approval_steps_separated(self):
        structured = {
            "root_cause": "Bad deploy",
            "confidence": "high",
            "evidence": [],
            "remediation_steps": [
                "[NEEDS APPROVAL] Request manual rollback",
                "[AUTO-SAFE] Review handler code",
                "[HUMAN APPROVAL] Run load test before re-deploy",
            ],
            "postmortem_summary": "",
        }
        r = _parse_crew_output("", structured, self._alert())
        assert len(r.needs_approval) == 2
        assert len(r.remediation_steps) == 1

    def test_prose_fallback_extracts_root_cause(self):
        # Prose fallback expects the root cause content on the line AFTER the marker
        raw = "**Root cause**\nMemory leak in Stripe webhook handler\nConfidence: high"
        r = _parse_crew_output(raw, None, self._alert())
        assert r.root_cause
        assert "memory" in r.root_cause.lower() or "leak" in r.root_cause.lower()

    def test_prose_fallback_extracts_confidence(self):
        raw = "confidence level: medium\nroot cause: disk pressure"
        r = _parse_crew_output(raw, None, self._alert())
        assert r.confidence == "medium"

    def test_empty_output_sets_fallback_root_cause(self):
        r = _parse_crew_output("", {}, self._alert())
        assert r.root_cause  # never empty — uses fallback text

    def test_alert_metadata_preserved(self):
        r = _parse_crew_output("", {}, self._alert())
        assert r.alert_title == "OOMKilled"
        assert r.service == "checkout"
        assert r.severity == "critical"


# ── Escalation gate (pure logic) ──────────────────────────────────────────

class TestEscalationGate:
    def _make(self, severity, steps=None, approval=None):
        return TriageResult(
            alert_title="Test Alert",
            service="svc",
            severity=severity,
            remediation_steps=steps or [],
            needs_approval=approval or [],
        )

    def _gate(self, r):
        can_resolve = bool(r.remediation_steps) and not bool(r.needs_approval)
        needs_page = r.severity in ("critical", "high") and not can_resolve
        return can_resolve, needs_page

    def test_auto_steps_no_approval_no_escalation(self):
        r = self._make("critical", steps=["[AUTO-SAFE] restart"])
        assert self._gate(r) == (True, False)

    def test_needs_approval_escalates(self):
        r = self._make("critical", approval=["[NEEDS APPROVAL] rollback"])
        assert self._gate(r) == (False, True)

    def test_mixed_steps_with_approval_escalates(self):
        r = self._make("high", steps=["[AUTO-SAFE] check logs"], approval=["[NEEDS APPROVAL] rollback"])
        assert self._gate(r) == (False, True)

    def test_no_steps_high_critical_escalates(self):
        assert self._gate(self._make("high")) == (False, True)
        assert self._gate(self._make("critical")) == (False, True)

    def test_no_steps_medium_low_no_escalation(self):
        assert self._gate(self._make("medium"))[1] is False
        assert self._gate(self._make("low"))[1] is False
