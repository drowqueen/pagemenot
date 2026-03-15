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
        assert _dedup_key(fire["service"], fire["title"]) == _dedup_key(
            resolve["service"], resolve["title"]
        )

    def test_pagerduty_returns_required_fields(self):
        p = _parse_alert(
            "pagerduty",
            {
                "title": "High error rate on payment-service",
                "service": {"name": "payment-service"},
                "urgency": "high",
            },
        )
        assert p["title"]
        assert p["severity"] in ("critical", "high", "medium", "low", "unknown")

    def test_grafana_returns_required_fields(self):
        p = _parse_alert(
            "grafana",
            {
                "status": "firing",
                "title": "High latency",
                "ruleName": "HighLatency",
            },
        )
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
        r = _parse_crew_output("", self._alert())
        assert r.root_cause
        assert r.needs_approval == []

    def test_needs_approval_steps_separated(self):
        raw = "[NEEDS APPROVAL] Request manual rollback\n[AUTO-SAFE] Review handler code\n[HUMAN APPROVAL] Run load test"
        r = _parse_crew_output(raw, self._alert())
        assert len(r.needs_approval) == 2
        assert len(r.remediation_steps) == 1

    def test_prose_fallback_extracts_root_cause(self):
        # Prose fallback expects the root cause content on the line AFTER the marker
        raw = "**Root cause**\nMemory leak in Stripe webhook handler\nConfidence: high"
        r = _parse_crew_output(raw, self._alert())
        assert r.root_cause
        assert "memory" in r.root_cause.lower() or "leak" in r.root_cause.lower()

    def test_prose_fallback_extracts_confidence(self):
        raw = "confidence level: medium\nroot cause: disk pressure"
        r = _parse_crew_output(raw, self._alert())
        assert r.confidence == "medium"

    def test_empty_output_sets_fallback_root_cause(self):
        r = _parse_crew_output("", self._alert())
        assert r.root_cause  # never empty — uses fallback text

    def test_alert_metadata_preserved(self):
        r = _parse_crew_output("", self._alert())
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
        r = self._make(
            "high", steps=["[AUTO-SAFE] check logs"], approval=["[NEEDS APPROVAL] rollback"]
        )
        assert self._gate(r) == (False, True)

    def test_no_steps_high_critical_escalates(self):
        assert self._gate(self._make("high")) == (False, True)
        assert self._gate(self._make("critical")) == (False, True)

    def test_no_steps_medium_low_no_escalation(self):
        assert self._gate(self._make("medium"))[1] is False
        assert self._gate(self._make("low"))[1] is False


# ── TestParseAlertGCP ─────────────────────────────────────────────────────


class TestParseAlertGCP:
    # GCP-02: New Relic
    def test_newrelic_gcp_cloud_provider(self):
        payload = {
            "condition_name": "Host not reporting",
            "severity": "CRITICAL",
            "targets": [{"name": "gcp-app-vm", "labels": {"provider": "GCP"}}],
        }
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["gcp"]

    def test_newrelic_gcp_cloud_label(self):
        payload = {
            "condition_name": "Host not reporting",
            "severity": "CRITICAL",
            "targets": [{"name": "gcp-app-vm", "labels": {"cloud": "google"}}],
        }
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["gcp"]

    def test_newrelic_aws_provider_label(self):
        payload = {
            "condition_name": "RDS CPU high",
            "severity": "CRITICAL",
            "targets": [{"name": "rds-prod", "labels": {"provider": "AWS"}}],
        }
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["aws"]

    def test_newrelic_amazon_cloud_label(self):
        payload = {
            "condition_name": "EC2 down",
            "severity": "CRITICAL",
            "targets": [{"name": "web-01", "labels": {"cloud": "amazon"}}],
        }
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["aws"]

    def test_grafana_aws_keyword_fallback(self):
        payload = {
            "title": "AWS RDS connection pool exhausted",
            "alerts": [{"labels": {"alertname": "AWS RDS connection pool exhausted"}}],
        }
        p = _parse_alert("grafana", payload)
        assert p["cloud_provider"] == ["aws"]

    def test_newrelic_no_provider_cloud_provider(self):
        payload = {
            "condition_name": "Host not reporting",
            "severity": "CRITICAL",
            "targets": [{"name": "some-host", "labels": {"hostname": "some-host"}}],
        }
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["generic"]

    def test_newrelic_empty_targets_cloud_provider(self):
        payload = {"condition_name": "Test", "severity": "CRITICAL", "targets": []}
        p = _parse_alert("newrelic", payload)
        assert p["cloud_provider"] == ["generic"]

    # GCP-03: Grafana
    def test_grafana_gcp_cloud_provider(self):
        payload = {
            "title": "GCP VM Down",
            "alerts": [
                {"labels": {"alertname": "GCP VM Down", "service": "gcp-app-vm", "cloud": "gcp"}}
            ],
        }
        p = _parse_alert("grafana", payload)
        assert p["cloud_provider"] == ["gcp"]

    def test_grafana_gcp_keyword_fallback(self):
        payload = {
            "title": "GCE instance stopped",
            "alerts": [{"labels": {"alertname": "GCE instance stopped", "service": "gcp-app-vm"}}],
        }
        p = _parse_alert("grafana", payload)
        assert p["cloud_provider"] == ["gcp"]

    def test_grafana_no_cloud_label_cloud_provider(self):
        payload = {
            "title": "High latency",
            "alerts": [{"labels": {"alertname": "HighLatency", "service": "payment-service"}}],
        }
        p = _parse_alert("grafana", payload)
        assert p["cloud_provider"] == ["generic"]

    # GCP-01: Cloud Monitoring (already working — regression guard)
    def test_generic_gce_instance_cloud_provider(self):
        payload = {
            "incident": {
                "condition_name": "gcp-app-vm instance stopped",
                "state": "open",
                "resource": {"type": "gce_instance", "labels": {"instance_name": "gcp-app-vm"}},
                "resource_display_name": "gcp-app-vm",
            }
        }
        p = _parse_alert("generic", payload)
        assert p["cloud_provider"] == ["gcp"]
        assert p["service"] == "gcp-app-vm"

    def test_generic_uptime_url_cloud_run_cloud_provider(self):
        payload = {
            "incident": {
                "condition_name": "Cloud Run uptime check",
                "state": "open",
                "resource": {
                    "type": "uptime_url",
                    "labels": {"host": "gcp-hello-00001-779-uc.a.run.app"},
                },
            }
        }
        p = _parse_alert("generic", payload)
        assert p["cloud_provider"] == ["gcp"]
        assert p["service"] == "gcp-hello"

    def test_generic_uptime_url_cloud_run_random_suffix(self):
        """Real CM webhook sends hash suffix e.g. gcp-hello-boqrqyvx4a-uc.a.run.app."""
        payload = {
            "incident": {
                "condition_name": "Cloud Run uptime check",
                "state": "open",
                "resource": {
                    "type": "uptime_url",
                    "labels": {"host": "gcp-hello-boqrqyvx4a-uc.a.run.app"},
                },
            }
        }
        p = _parse_alert("generic", payload)
        assert p["cloud_provider"] == ["gcp"]
        assert p["service"] == "gcp-hello"


# ── Azure Monitor alert fixtures ──────────────────────────────────────────

AZURE_VM_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertId": "/subscriptions/sub123/providers/Microsoft.AlertsManagement/alerts/abc",
            "alertRule": "VM CPU High",
            "severity": "Sev1",
            "monitorCondition": "Fired",
            "alertTargetIDs": [
                "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.compute/virtualmachines/my-vm"
            ],
            "configurationItems": ["my-vm"],
            "firedDateTime": "2026-03-11T10:00:00Z",
            "description": "CPU > 90% for 5 minutes",
        },
        "alertContext": {},
    },
}

AZURE_APP_SERVICE_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertRule": "App Service Unavailable",
            "severity": "Sev0",
            "monitorCondition": "Fired",
            "alertTargetIDs": [
                "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.web/sites/my-app"
            ],
            "configurationItems": ["my-app"],
            "description": "HTTP 5xx rate > 50%",
        },
        "alertContext": {},
    },
}

AZURE_RESOLVED_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertRule": "VM CPU High",
            "severity": "Sev1",
            "monitorCondition": "Resolved",
            "alertTargetIDs": [
                "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.compute/virtualmachines/my-vm"
            ],
            "configurationItems": ["my-vm"],
            "description": "",
        },
        "alertContext": {},
    },
}


# ── TestParseAlertAzure ────────────────────────────────────────────────────


class TestParseAlertAzure:
    def test_fired_fields(self):
        p = _parse_alert("azure", AZURE_VM_ALERT)
        assert p["title"] == "VM CPU High"
        assert p["service"] == "my-vm"
        assert p["cloud_provider"] == ["azure"]
        assert p["severity"] in ("critical", "high", "medium", "low", "unknown")

    def test_app_service_service_extraction(self):
        p = _parse_alert("azure", AZURE_APP_SERVICE_ALERT)
        assert p["service"] == "my-app"

    def test_resolved_parseable(self):
        p = _parse_alert("azure", AZURE_RESOLVED_ALERT)
        assert isinstance(p, dict)
        assert "service" in p

    @pytest.mark.parametrize(
        "sev_input,expected",
        [
            ("Sev0", "critical"),
            ("Sev1", "high"),
            ("Sev2", "medium"),
            ("Sev3", "low"),
            ("Sev4", "low"),
        ],
    )
    def test_severity_mapping(self, sev_input, expected):
        payload = {
            "schemaId": "azureMonitorCommonAlertSchema",
            "data": {
                "essentials": {
                    "alertRule": "Test Alert",
                    "severity": sev_input,
                    "monitorCondition": "Fired",
                    "alertTargetIDs": [
                        "/subscriptions/sub123/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm"
                    ],
                    "configurationItems": ["vm"],
                    "description": "test",
                },
                "alertContext": {},
            },
        }
        p = _parse_alert("azure", payload)
        assert p["severity"] == expected

    def test_service_from_last_segment(self):
        target = AZURE_VM_ALERT["data"]["essentials"]["alertTargetIDs"][0]
        last_segment = target.split("/")[-1]
        p = _parse_alert("azure", AZURE_VM_ALERT)
        assert p["service"] == last_segment

    def test_legacy_payload_no_essentials(self):
        p = _parse_alert("azure", {"data": {}})
        assert isinstance(p, dict)
        assert p["cloud_provider"] == ["azure"]


# ── TestDispatchExecAzure ─────────────────────────────────────────────────


from unittest.mock import patch  # noqa: E402


class TestDispatchExecAzure:
    def test_az_routes_to_exec_shell(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_shell") as mock_shell:
            mock_shell.return_value = "ok"
            dispatch_exec_step(
                "<!-- exec: az vm start --resource-group my-rg --name my-vm -->", "my-vm"
            )
        mock_shell.assert_called_once()
