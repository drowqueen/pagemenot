"""Unit tests for pagemenot.triage — pure functions only."""

import time

import pytest

from pagemenot.triage import (
    TriageResult,
    _active_incidents,
    _check_and_register,
    _dedup_key,
    _dedup_lock,
    _parse_alert,
    _parse_azure_resource_path,
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


# ── Dynamic resource context ───────────────────────────────────────────────


class TestParseAzureResourcePath:
    def test_postgres_flexible_server(self):
        path = "/subscriptions/sub-123/resourceGroups/prod-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/my-postgres"
        ctx = _parse_azure_resource_path(path)
        assert ctx["subscription_id"] == "sub-123"
        assert ctx["resource_group"] == "prod-rg"
        assert ctx["flexibleservers"] == "my-postgres"
        assert ctx["resource_name"] == "my-postgres"

    def test_sql_server_with_database(self):
        path = "/subscriptions/sub-abc/resourceGroups/data-rg/providers/Microsoft.Sql/servers/sql-srv/databases/mydb"
        ctx = _parse_azure_resource_path(path)
        assert ctx["subscription_id"] == "sub-abc"
        assert ctx["resource_group"] == "data-rg"
        assert ctx["servers"] == "sql-srv"
        assert ctx["databases"] == "mydb"
        assert ctx["resource_name"] == "mydb"

    def test_app_service_site(self):
        path = "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.web/sites/my-app"
        ctx = _parse_azure_resource_path(path)
        assert ctx["resource_group"] == "my-rg"
        assert ctx["sites"] == "my-app"
        assert ctx["resource_name"] == "my-app"

    def test_redis_cache(self):
        path = (
            "/subscriptions/sub-x/resourceGroups/cache-rg/providers/Microsoft.Cache/Redis/my-redis"
        )
        ctx = _parse_azure_resource_path(path)
        assert ctx["resource_group"] == "cache-rg"
        assert ctx["redis"] == "my-redis"


class TestResourceCtxAzureParse:
    def _azure_postgres_payload(self, rg="prod-rg", server="my-postgres"):
        return {
            "schemaId": "azureMonitorCommonAlertSchema",
            "data": {
                "essentials": {
                    "alertRule": "PostgreSQL Down",
                    "severity": "Sev1",
                    "monitorCondition": "Fired",
                    "alertTargetIDs": [
                        f"/subscriptions/sub-123/resourceGroups/{rg}/providers/Microsoft.DBforPostgreSQL/flexibleServers/{server}"
                    ],
                    "configurationItems": [server],
                    "targetResourceRegion": "eastus",
                    "description": "PostgreSQL flexible server unreachable",
                },
                "alertContext": {},
            },
        }

    def test_resource_group_in_ctx(self):
        p = _parse_alert("azure", self._azure_postgres_payload(rg="prod-rg"))
        assert p["resource_ctx"]["resource_group"] == "prod-rg"

    def test_flexibleservers_in_ctx(self):
        p = _parse_alert("azure", self._azure_postgres_payload(server="my-postgres"))
        assert p["resource_ctx"]["flexibleservers"] == "my-postgres"

    def test_region_in_ctx(self):
        p = _parse_alert("azure", self._azure_postgres_payload())
        assert p["resource_ctx"]["region"] == "eastus"

    def test_resource_name_is_last_segment(self):
        p = _parse_alert("azure", self._azure_postgres_payload(server="pg-prod-01"))
        assert p["resource_ctx"]["resource_name"] == "pg-prod-01"

    def test_different_server_name_flows_through(self):
        p1 = _parse_alert("azure", self._azure_postgres_payload(server="pg-east"))
        p2 = _parse_alert("azure", self._azure_postgres_payload(server="pg-west"))
        assert p1["resource_ctx"]["flexibleservers"] == "pg-east"
        assert p2["resource_ctx"]["flexibleservers"] == "pg-west"

    def test_multi_target_extra_resource_ctxs_populated(self):
        payload = {
            "schemaId": "azureMonitorCommonAlertSchema",
            "data": {
                "essentials": {
                    "alertRule": "PostgreSQL Down",
                    "severity": "Sev1",
                    "monitorCondition": "Fired",
                    "alertTargetIDs": [
                        "/subscriptions/sub-123/resourceGroups/prod-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-east",
                        "/subscriptions/sub-123/resourceGroups/prod-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-west",
                    ],
                    "configurationItems": ["pg-east"],
                    "description": "Two servers down",
                },
                "alertContext": {},
            },
        }
        p = _parse_alert("azure", payload)
        assert p["resource_ctx"]["flexibleservers"] == "pg-east"
        assert len(p["extra_resource_ctxs"]) == 1
        assert p["extra_resource_ctxs"][0]["flexibleservers"] == "pg-west"
        assert p["extra_resource_ctxs"][0]["resource_group"] == "prod-rg"

    def test_single_target_extra_resource_ctxs_empty(self):
        p = _parse_alert("azure", self._azure_postgres_payload())
        assert p["extra_resource_ctxs"] == []


class TestResourceCtxGCPParse:
    def _gcp_cloud_sql_payload(self, project="my-project", zone="us-central1-a"):
        return {
            "incident": {
                "condition_name": "Cloud SQL Unavailable",
                "state": "open",
                "resource": {
                    "type": "cloudsql_database",
                    "labels": {
                        "database_id": f"{project}:my-sql",
                        "project_id": project,
                        "region": "us-central1",
                        "zone": zone,
                    },
                },
                "resource_display_name": "my-sql",
            }
        }

    def test_project_id_in_ctx(self):
        p = _parse_alert("generic", self._gcp_cloud_sql_payload(project="zipintel"))
        assert p["resource_ctx"]["project_id"] == "zipintel"

    def test_region_in_ctx(self):
        p = _parse_alert("generic", self._gcp_cloud_sql_payload())
        assert p["resource_ctx"]["region"] == "us-central1"

    def test_zone_in_ctx(self):
        p = _parse_alert("generic", self._gcp_cloud_sql_payload(zone="us-central1-b"))
        assert p["resource_ctx"]["zone"] == "us-central1-b"

    def test_different_project_flows_through(self):
        p = _parse_alert("generic", self._gcp_cloud_sql_payload(project="other-proj"))
        assert p["resource_ctx"]["project_id"] == "other-proj"


class TestResourceCtxAWSSNS:
    def _sns_payload(self, service="nginx-prod", region="eu-west-1", account="123456789"):
        return {
            "title": "EC2 Nginx Down",
            "service": service,
            "region": region,
            "account_id": account,
            "severity": "high",
            "alarm_name": "EC2-Nginx-Health",
            "message": "nginx service stopped",
        }

    def test_resource_name_in_ctx(self):
        p = _parse_alert("sns", self._sns_payload(service="nginx-prod"))
        assert p["resource_ctx"]["resource_name"] == "nginx-prod"

    def test_region_in_ctx(self):
        p = _parse_alert("sns", self._sns_payload(region="us-east-1"))
        assert p["resource_ctx"]["region"] == "us-east-1"

    def test_account_id_in_ctx(self):
        p = _parse_alert("sns", self._sns_payload(account="999000111"))
        assert p["resource_ctx"]["account_id"] == "999000111"

    def test_different_service_flows_through(self):
        p = _parse_alert("sns", self._sns_payload(service="rds-prod"))
        assert p["resource_ctx"]["resource_name"] == "rds-prod"


class TestResourceCtxGrafanaK8s:
    """Grafana alert with k8s labels — namespace + service flow to resource_ctx."""

    def _grafana_k8s_payload(self, service="checkout", namespace="production"):
        return {
            "title": "Pod CrashLoopBackOff",
            "alerts": [
                {
                    "labels": {
                        "alertname": "PodCrashLoopBackOff",
                        "service": service,
                        "namespace": namespace,
                        "severity": "critical",
                    }
                }
            ],
        }

    def test_namespace_in_ctx(self):
        p = _parse_alert("grafana", self._grafana_k8s_payload(namespace="production"))
        assert p["resource_ctx"]["namespace"] == "production"

    def test_service_in_ctx(self):
        p = _parse_alert("grafana", self._grafana_k8s_payload(service="checkout"))
        assert p["resource_ctx"]["service"] == "checkout"

    def test_different_namespace_flows_through(self):
        p = _parse_alert("grafana", self._grafana_k8s_payload(namespace="staging"))
        assert p["resource_ctx"]["namespace"] == "staging"

    def test_cloud_provider_is_generic_for_onprem(self):
        p = _parse_alert("grafana", self._grafana_k8s_payload())
        assert p["cloud_provider"] == ["generic"]


class TestTemplateSubstitution:
    """dispatch_exec_step resolves {{ vars }} from resource_ctx before execution."""

    def test_azure_resource_group_substituted(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_shell") as mock_shell:
            mock_shell.return_value = "ok"
            dispatch_exec_step(
                "<!-- exec: az postgres flexible-server show --name {{ service }} --resource-group {{ resource_group }} -->",
                "my-postgres",
                resource_ctx={"resource_group": "prod-rg"},
            )
        cmd = mock_shell.call_args[0][0]
        assert "--resource-group prod-rg" in cmd
        assert "--name my-postgres" in cmd
        assert "{{" not in cmd

    def test_gcp_project_id_substituted(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_shell") as mock_shell:
            mock_shell.return_value = "ok"
            dispatch_exec_step(
                "<!-- exec: gcloud sql instances restart {{ service }} --project={{ project_id }} --quiet -->",
                "my-sql",
                resource_ctx={"project_id": "zipintel"},
            )
        cmd = mock_shell.call_args[0][0]
        assert "--project=zipintel" in cmd
        assert "my-sql" in cmd
        assert "{{" not in cmd

    def test_aws_service_substituted(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_aws") as mock_aws:
            mock_aws.return_value = "{}"
            dispatch_exec_step(
                "<!-- exec: aws rds start-db-instance --db-instance-identifier {{ service }} -->",
                "rds-prod",
                resource_ctx={"resource_name": "rds-prod"},
            )
        # exec_aws is called with (service, action, params, ...) — just confirm no unresolved vars
        # by checking dispatch did not raise
        mock_aws.assert_called_once()

    def test_k8s_namespace_from_grafana_ctx(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_kubectl") as mock_kubectl:
            mock_kubectl.return_value = "pod/checkout running"
            dispatch_exec_step(
                "<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->",
                "checkout",
                resource_ctx={"namespace": "production"},
            )
        cmd = mock_kubectl.call_args[0][0]
        assert "-n production" in cmd
        assert "-l app=checkout" in cmd
        assert "{{" not in cmd

    def test_unresolved_var_raises(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_shell"):
            with pytest.raises(ValueError, match="Unresolved template variables"):
                dispatch_exec_step(
                    "<!-- exec: az group show --name {{ missing_var }} -->",
                    "svc",
                    resource_ctx={},
                )

    def test_multiple_vars_all_substituted(self):
        from pagemenot.tools import dispatch_exec_step

        with patch("pagemenot.tools.exec_shell") as mock_shell:
            mock_shell.return_value = "ok"
            dispatch_exec_step(
                "<!-- exec: az postgres flexible-server start --name {{ flexibleservers }} --resource-group {{ resource_group }} --subscription {{ subscription_id }} -->",
                "pg-prod",
                resource_ctx={
                    "flexibleservers": "pg-prod",
                    "resource_group": "prod-rg",
                    "subscription_id": "sub-123",
                },
            )
        cmd = mock_shell.call_args[0][0]
        assert "pg-prod" in cmd
        assert "prod-rg" in cmd
        assert "sub-123" in cmd
        assert "{{" not in cmd
