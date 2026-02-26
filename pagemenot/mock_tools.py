"""
Mock integration layer — returns realistic fake data when real tools aren't configured.

This is the KEY to the cloud-agnostic POC. The mock layer:
1. Auto-activates when a real integration isn't configured
2. Returns realistic data matching real tool output formats
3. Is seeded by the incident simulator's scenario data
4. Lets teams demo Pagemenot BEFORE connecting real monitoring

When a real integration IS configured, the mock is bypassed automatically.
Teams never configure this — it's fully transparent.
"""

import json
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from crewai.tools import tool
from pagemenot.config import settings

logger = logging.getLogger("pagemenot.mocks")

# ══════════════════════════════════════════════════════════════
# MOCK DATA STORE
#
# The incident simulator POSTs scenario data to /webhooks/mock-context
# before firing the alert. This gives the mock tools realistic data
# to return. If no mock data is seeded, tools return plausible defaults.
# ══════════════════════════════════════════════════════════════

_mock_context: dict = {}


def seed_mock_context(scenario_data: dict):
    """Called by the simulator to pre-load realistic data."""
    global _mock_context
    _mock_context = scenario_data
    logger.debug(f"Mock context seeded for service: {scenario_data.get('service', '?')}")


def clear_mock_context():
    global _mock_context
    _mock_context = {}


# ══════════════════════════════════════════════════════════════
# MOCK MONITOR TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Query Prometheus Metrics")
def mock_prometheus(service_name: str) -> str:
    """Query Prometheus for key metrics of a service: error rate, latency,
    CPU, memory, and pod restarts. Input should be the service name."""
    metrics = _mock_context.get("mock_metrics", {})

    if not metrics:
        # Generate plausible defaults
        metrics = {
            "error_rate": {"before": round(random.uniform(0, 1), 2), "after": round(random.uniform(5, 30), 1), "unit": "%"},
            "request_rate": {"before": random.randint(100, 2000), "after": random.randint(100, 2000), "unit": "req/s"},
            "latency_p99": {"before": round(random.uniform(0.01, 0.2), 3), "after": round(random.uniform(0.5, 5), 2), "unit": "s"},
            "cpu_percent": {"before": random.randint(20, 50), "after": random.randint(50, 95), "unit": "%"},
            "memory_mb": {"before": random.randint(200, 1000), "after": random.randint(500, 2048), "unit": "MB"},
            "pod_restarts": {"before": 0, "after": random.randint(0, 10), "unit": ""},
        }

    lines = [f"Prometheus metrics for '{service_name}' (last 30min):"]
    for name, data in metrics.items():
        before = data["before"]
        after = data["after"]
        unit = data["unit"]
        change = after - before
        arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
        lines.append(f"  {name}: {after}{unit} ({arrow} from {before}{unit})")

    return "\n".join(lines)


@tool("Search Logs in Loki")
def mock_loki(query: str) -> str:
    """Search Loki for log entries matching a query.
    Input: service name with keywords like 'payment-service error'."""
    logs = _mock_context.get("mock_logs", [])

    if not logs:
        return f"No log entries found matching '{query}' in the last 30 minutes."

    lines = [f"Loki logs (last 30min, {len(logs)} entries):"]
    for log_line in logs:
        lines.append(f"  {log_line}")

    return "\n".join(lines)


@tool("Get PagerDuty Incident Details")
def mock_pagerduty(incident_id_or_description: str) -> str:
    """Get PagerDuty incident details. Input: incident ID or search term."""
    pd = _mock_context.get("pagerduty", {})

    if not pd:
        return f"No PagerDuty incidents matching '{incident_id_or_description}'."

    return (
        f"PagerDuty Incident {pd.get('id', 'P0000000')}:\n"
        f"  Title: {pd.get('title', 'Unknown')}\n"
        f"  Status: triggered\n"
        f"  Urgency: {pd.get('urgency', 'high')}\n"
        f"  Service: {pd.get('service', {}).get('name', 'unknown')}\n"
        f"  Description: {pd.get('description', 'N/A')}"
    )


@tool("Get Grafana Alert History")
def mock_grafana(service_name: str) -> str:
    """Get recent Grafana alerts for a service. Input: service name."""
    pd = _mock_context.get("pagerduty", {})
    title = pd.get("title", f"{service_name} alert")

    return (
        f"Grafana alerts for '{service_name}':\n"
        f"  - {title}: FIRING since {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
        f"  - Dashboard: https://grafana.internal/d/{service_name}"
    )


@tool("Get OpsGenie Alert Details")
def mock_opsgenie(alert_id_or_service: str) -> str:
    """Get OpsGenie alert details. Input: alert ID or service name."""
    pd = _mock_context.get("pagerduty", {})
    return (
        f"OpsGenie Alert (mock):\n"
        f"  Message: {pd.get('title', f'{alert_id_or_service} alert')}\n"
        f"  Priority: P2\n"
        f"  Status: open\n"
        f"  Entity: {pd.get('service', {}).get('name', alert_id_or_service)}"
    )


@tool("Query Datadog Metrics")
def mock_datadog(service_name: str) -> str:
    """Query Datadog for service metrics. Input: service name."""
    metrics = _mock_context.get("mock_metrics", {})
    if not metrics:
        return f"Datadog metrics for '{service_name}': no data in last 30min."
    lines = [f"Datadog metrics for '{service_name}' (last 30min):"]
    for name, data in metrics.items():
        lines.append(f"  {name}: {data['after']}{data['unit']}")
    return "\n".join(lines)


@tool("Query New Relic Metrics")
def mock_newrelic(service_name: str) -> str:
    """Query New Relic for service metrics. Input: service name."""
    metrics = _mock_context.get("mock_metrics", {})
    err = metrics.get("error_rate", {}).get("after", "N/A")
    lat = metrics.get("latency_p99", {}).get("after", "N/A")
    return (
        f"New Relic metrics for '{service_name}' (last 30min):\n"
        f"  error_rate: {err}%\n"
        f"  avg_duration: {lat}s"
    )


# ══════════════════════════════════════════════════════════════
# MOCK DIAGNOSER TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Get Recent Deploys from GitHub")
def mock_github_deploys(repo_or_service: str) -> str:
    """Get recent deploys for a repo/service. Input: service or repo name."""
    deploys = _mock_context.get("mock_deploys", [])

    if not deploys:
        return f"No recent deploys found for '{repo_or_service}' in the last 48 hours."

    lines = [f"Recent deploys for '{repo_or_service}':"]
    for d in deploys:
        lines.append(
            f"  PR #{d['pr']}: {d['title']}\n"
            f"    Author: {d['author']}\n"
            f"    Merged: {d['merged_at']}\n"
            f"    Files: {', '.join(d['files_changed'])}"
        )

    return "\n".join(lines)


@tool("Get Pull Request Diff")
def mock_github_diff(repo_and_pr: str) -> str:
    """Get the diff from a PR. Input: 'repo#number' like 'payment-service#891'."""
    deploys = _mock_context.get("mock_deploys", [])

    # Try to match the PR number
    pr_num = None
    if "#" in repo_and_pr:
        try:
            pr_num = int(repo_and_pr.split("#")[1])
        except ValueError:
            pass

    for d in deploys:
        if pr_num and d["pr"] == pr_num:
            return (
                f"PR #{d['pr']}: {d['title']}\n"
                f"Author: {d['author']}\n"
                f"Files changed: {', '.join(d['files_changed'])}\n\n"
                f"Diff preview:\n{d.get('diff_preview', 'No diff available')}"
            )

    if deploys:
        d = deploys[0]
        return (
            f"PR #{d['pr']}: {d['title']}\n"
            f"Diff preview:\n{d.get('diff_preview', 'No diff available')}"
        )

    return f"No PR diff available for '{repo_and_pr}'."


# ══════════════════════════════════════════════════════════════
# MOCK REMEDIATOR TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Kubernetes Status Check")
def mock_kubernetes(service_or_namespace: str) -> str:
    """Check Kubernetes pod/deployment status. Input: service name."""
    k8s = _mock_context.get("mock_k8s", {})

    if not k8s:
        return f"Kubernetes status for '{service_or_namespace}': 3/3 pods Running, no issues."

    return (
        f"Kubernetes status for '{service_or_namespace}':\n"
        f"  Pods: {k8s.get('pods', 'unknown')}\n"
        f"  Restarts (30min): {k8s.get('restarts', 0)}\n"
        f"  Events: {k8s.get('events', 'none')}\n"
        f"  Resource pressure: {'YES' if k8s.get('resource_pressure') else 'No'}"
    )


# ══════════════════════════════════════════════════════════════
# AUTO-DETECTION: real vs mock tools
# ══════════════════════════════════════════════════════════════

def get_available_tools() -> dict[str, list]:
    """Return tools grouped by agent role.

    For each integration:
    - If configured in .env → return REAL tool
    - If not configured → return MOCK tool (with realistic data)
    """
    from pagemenot.tools import (
        query_prometheus, search_logs_loki, get_pagerduty_incident,
        query_grafana_alerts, get_recent_deploys, get_pr_diff,
        search_past_incidents, search_runbooks, request_human_approval,
        kubectl_rollback, get_opsgenie_alert, query_datadog_metrics,
        query_newrelic_metrics,
    )

    def _pick(condition, real, mock, label):
        if condition:
            logger.info(f"✅ {label}: LIVE")
            return real
        logger.info(f"🔶 {label}: MOCK")
        return mock

    monitor_tools = [
        _pick(settings.prometheus_url,             query_prometheus,       mock_prometheus,    "Prometheus"),
        _pick(settings.loki_url,                   search_logs_loki,       mock_loki,          "Loki"),
        _pick(settings.grafana_url,                query_grafana_alerts,   mock_grafana,       "Grafana"),
        _pick(settings.datadog_api_key,            query_datadog_metrics,  mock_datadog,       "Datadog"),
        _pick(settings.newrelic_api_key,           query_newrelic_metrics, mock_newrelic,      "New Relic"),
        _pick(settings.pagerduty_api_key,          get_pagerduty_incident, mock_pagerduty,     "PagerDuty"),
        _pick(settings.opsgenie_api_key,           get_opsgenie_alert,     mock_opsgenie,      "OpsGenie"),
    ]

    diagnoser_tools = [
        *(_pick(settings.github_token, [get_recent_deploys, get_pr_diff], [mock_github_deploys, mock_github_diff], "GitHub")),
        search_past_incidents,
    ]
    logger.info("✅ Incident RAG: LIVE (local ChromaDB)")

    remediator_tools = [
        search_runbooks,
        request_human_approval,
        _pick(settings.kubeconfig_path, kubectl_rollback, mock_kubernetes, "Kubernetes"),
    ]

    return {
        "monitor": monitor_tools,
        "diagnoser": diagnoser_tools,
        "remediator": remediator_tools,
    }
