"""
Auto-discovery of tools based on what's configured in .env.

This is the core of the "zero config" experience:
- Team adds PROMETHEUS_URL to .env → MonitorAgent gets Prometheus tool
- Team adds GITHUB_TOKEN → DiagnoserAgent gets GitHub deploy history tool
- No tool config? Agents still work with whatever IS available

Each tool is a CrewAI @tool that wraps the actual API call.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from crewai.tools import tool

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.tools")


# ══════════════════════════════════════════════════════════════
# TOOL REGISTRY — auto-populates based on .env
# ══════════════════════════════════════════════════════════════

def get_available_tools() -> dict[str, list]:
    """Discover and return tools grouped by agent role.

    Called once at startup. Checks which integrations are
    configured and returns only the tools that will work.
    """
    monitor_tools = []
    diagnoser_tools = []
    remediator_tools = []

    # ── Monitor: metrics ──────────────────────────────────
    if settings.prometheus_url:
        monitor_tools.append(query_prometheus)
        logger.info("✅ Prometheus connected")

    if settings.grafana_url and settings.grafana_api_key:
        monitor_tools.append(query_grafana_alerts)
        logger.info("✅ Grafana connected")

    if settings.loki_url:
        monitor_tools.append(search_logs_loki)
        logger.info("✅ Loki connected")

    if settings.datadog_api_key:
        monitor_tools.append(query_datadog_metrics)
        logger.info("✅ Datadog connected")

    if settings.newrelic_api_key:
        monitor_tools.append(query_newrelic_metrics)
        logger.info("✅ New Relic connected")

    # ── Monitor: alerting / on-call ───────────────────────
    if settings.pagerduty_api_key:
        monitor_tools.append(get_pagerduty_incident)
        logger.info("✅ PagerDuty connected")

    if settings.opsgenie_api_key:
        monitor_tools.append(get_opsgenie_alert)
        logger.info("✅ OpsGenie connected")

    # ── Diagnoser tools ───────────────────────────────────
    if settings.github_token:
        diagnoser_tools.append(get_recent_deploys)
        diagnoser_tools.append(get_pr_diff)
        logger.info("✅ GitHub connected")

    diagnoser_tools.append(search_past_incidents)
    logger.info("✅ Incident RAG ready")

    # ── Remediator tools ──────────────────────────────────
    remediator_tools.append(search_runbooks)
    remediator_tools.append(request_human_approval)

    if settings.kubeconfig_path:
        remediator_tools.append(kubectl_rollback)
        logger.info("✅ Kubernetes connected")

    unconfigured = [
        v for v, s in [
            ("PROMETHEUS_URL", settings.prometheus_url),
            ("DATADOG_API_KEY", settings.datadog_api_key),
            ("NEWRELIC_API_KEY", settings.newrelic_api_key),
            ("LOKI_URL", settings.loki_url),
            ("GRAFANA_URL", settings.grafana_url),
            ("PAGERDUTY_API_KEY", settings.pagerduty_api_key),
            ("OPSGENIE_API_KEY", settings.opsgenie_api_key),
            ("GITHUB_TOKEN", settings.github_token),
        ] if not s
    ]
    if unconfigured:
        logger.info(f"💡 Not configured (all optional): {', '.join(unconfigured)}")

    return {
        "monitor": monitor_tools,
        "diagnoser": diagnoser_tools,
        "remediator": remediator_tools,
    }


# ══════════════════════════════════════════════════════════════
# MONITOR TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Query Prometheus Metrics")
def query_prometheus(service_name: str) -> str:
    """Query Prometheus for key metrics of a service: error rate, latency,
    CPU, memory, and pod restarts over the last 30 minutes.
    Input should be the service name (e.g., 'payment-service')."""
    try:
        end = datetime.now(timezone.utc)

        queries = {
            "error_rate": (
                f'sum(rate(http_requests_total{{service="{service_name}",status=~"5.."}}[5m])) '
                f'/ sum(rate(http_requests_total{{service="{service_name}"}}[5m])) * 100'
            ),
            "request_rate": f'sum(rate(http_requests_total{{service="{service_name}"}}[5m]))',
            "latency_p99": (
                f'histogram_quantile(0.99, '
                f'sum(rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le))'
            ),
            "cpu_percent": f'avg(rate(container_cpu_usage_seconds_total{{pod=~"{service_name}.*"}}[5m])) * 100',
            "memory_mb": f'avg(container_memory_working_set_bytes{{pod=~"{service_name}.*"}}) / 1024 / 1024',
            "pod_restarts": f'sum(increase(kube_pod_container_status_restarts_total{{pod=~"{service_name}.*"}}[30m]))',
        }

        headers = {}
        if settings.prometheus_auth_token:
            headers["Authorization"] = f"Bearer {settings.prometheus_auth_token}"

        results = []
        with httpx.Client(timeout=10, headers=headers) as client:
            for name, query in queries.items():
                resp = client.get(
                    f"{settings.prometheus_url}/api/v1/query",
                    params={"query": query, "time": end.timestamp()},
                )
                data = resp.json()
                if data.get("status") == "success" and data["data"]["result"]:
                    value = data["data"]["result"][0]["value"][1]
                    results.append(f"  {name}: {float(value):.2f}")
                else:
                    results.append(f"  {name}: no data")

        return f"Prometheus metrics for '{service_name}' (last 30min):\n" + "\n".join(results)

    except Exception as e:
        return f"Prometheus query failed: {e}. Check PROMETHEUS_URL is correct."


@tool("Get Grafana Alert History")
def query_grafana_alerts(service_name: str) -> str:
    """Get recent Grafana alerts related to a service.
    Input should be the service name."""
    try:
        headers = {"Authorization": f"Bearer {settings.grafana_api_key}"}
        if settings.grafana_org_id:
            headers["X-Grafana-Org-Id"] = settings.grafana_org_id

        with httpx.Client(timeout=10, headers=headers) as client:
            resp = client.get(f"{settings.grafana_url}/api/v1/provisioning/alert-rules")
            rules = resp.json()

            relevant = [r for r in rules if service_name.lower() in str(r).lower()]
            if not relevant:
                return f"No Grafana alerts found for '{service_name}'."

            summaries = [
                f"  - {r.get('title', 'Unknown')}: {r.get('condition', 'N/A')}"
                for r in relevant[:5]
            ]
            return f"Grafana alerts for '{service_name}':\n" + "\n".join(summaries)

    except Exception as e:
        return f"Grafana query failed: {e}"


@tool("Search Logs in Loki")
def search_logs_loki(query: str) -> str:
    """Search Loki for log entries matching a query.
    Input should be a LogQL query or a service name with keywords
    like 'payment-service error' or '{app="checkout"} |= "exception"'."""
    try:
        if not query.startswith("{"):
            parts = query.split(maxsplit=1)
            service = parts[0]
            keywords = parts[1] if len(parts) > 1 else "error"
            logql = f'{{app="{service}"}} |= "{keywords}"'
        else:
            logql = query

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=30)

        headers = {}
        if settings.loki_auth_token:
            headers["Authorization"] = f"Bearer {settings.loki_auth_token}"
        if settings.loki_org_id:
            headers["X-Scope-OrgID"] = settings.loki_org_id

        with httpx.Client(timeout=10, headers=headers) as client:
            resp = client.get(
                f"{settings.loki_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": int(start.timestamp() * 1e9),
                    "end": int(end.timestamp() * 1e9),
                    "limit": 50,
                },
            )
            data = resp.json()

        streams = data.get("data", {}).get("result", [])
        if not streams:
            return f"No log entries found for query: {logql}"

        lines = []
        for stream in streams[:5]:
            for ts, line in stream.get("values", [])[:10]:
                lines.append(f"  {line[:200]}")

        return f"Loki logs ({len(lines)} entries, last 30min):\n" + "\n".join(lines)

    except Exception as e:
        return f"Loki query failed: {e}"


@tool("Get PagerDuty Incident Details")
def get_pagerduty_incident(incident_id_or_description: str) -> str:
    """Get details about a PagerDuty incident.
    Input can be an incident ID (like P1234567) or a search term."""
    try:
        with httpx.Client(timeout=10) as client:
            # Try as incident ID first
            if incident_id_or_description.startswith("P"):
                resp = client.get(
                    f"https://api.pagerduty.com/incidents/{incident_id_or_description}",
                    headers={
                        "Authorization": f"Token token={settings.pagerduty_api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    inc = resp.json()["incident"]
                    return (
                        f"PagerDuty Incident {inc['id']}:\n"
                        f"  Title: {inc['title']}\n"
                        f"  Status: {inc['status']}\n"
                        f"  Urgency: {inc['urgency']}\n"
                        f"  Service: {inc['service']['summary']}\n"
                        f"  Created: {inc['created_at']}\n"
                        f"  Assigned: {', '.join(a['summary'] for a in inc.get('assignments', []))}"
                    )

            # Fall back to search
            resp = client.get(
                "https://api.pagerduty.com/incidents",
                headers={
                    "Authorization": f"Token token={settings.pagerduty_api_key}",
                    "Content-Type": "application/json",
                },
                params={"sort_by": "created_at:desc", "limit": 5},
            )
            incidents = resp.json().get("incidents", [])
            if not incidents:
                return "No recent PagerDuty incidents found."

            lines = []
            for inc in incidents:
                lines.append(
                    f"  [{inc['id']}] {inc['title']} — {inc['status']} "
                    f"({inc['urgency']}) — {inc['service']['summary']}"
                )
            return "Recent PagerDuty incidents:\n" + "\n".join(lines)

    except Exception as e:
        return f"PagerDuty query failed: {e}"


@tool("Get OpsGenie Alert Details")
def get_opsgenie_alert(alert_id_or_service: str) -> str:
    """Get OpsGenie alert details. Input: alert ID or service name."""
    try:
        with httpx.Client(timeout=10) as client:
            if len(alert_id_or_service) == 36 and "-" in alert_id_or_service:
                resp = client.get(
                    f"https://api.opsgenie.com/v2/alerts/{alert_id_or_service}",
                    headers={"Authorization": f"GenieKey {settings.opsgenie_api_key}"},
                )
                if resp.status_code == 200:
                    a = resp.json()["data"]
                    return (
                        f"OpsGenie Alert {a['id']}:\n"
                        f"  Message: {a.get('message', 'N/A')}\n"
                        f"  Priority: {a.get('priority', 'N/A')}\n"
                        f"  Status: {a.get('status', 'N/A')}\n"
                        f"  Tags: {', '.join(a.get('tags', []))}\n"
                        f"  Created: {a.get('createdAt', 'N/A')}"
                    )

            resp = client.get(
                "https://api.opsgenie.com/v2/alerts",
                headers={"Authorization": f"GenieKey {settings.opsgenie_api_key}"},
                params={"query": alert_id_or_service, "limit": 5, "sort": "createdAt", "order": "desc"},
            )
            alerts = resp.json().get("data", [])
            if not alerts:
                return f"No OpsGenie alerts found for '{alert_id_or_service}'."

            lines = []
            for a in alerts:
                lines.append(f"  [{a['id'][:8]}] {a.get('message', '?')} — {a.get('status', '?')} ({a.get('priority', '?')})")
            return "Recent OpsGenie alerts:\n" + "\n".join(lines)

    except Exception as e:
        return f"OpsGenie query failed: {e}"


@tool("Query Datadog Metrics")
def query_datadog_metrics(service_name: str) -> str:
    """Query Datadog for service metrics over the last 30 minutes.
    Input: service name (e.g., 'payment-service')."""
    try:
        import time
        now = int(time.time())
        start = now - 1800

        queries = {
            "error_rate": f"sum:trace.http.request.errors{{service:{service_name}}}",
            "request_rate": f"sum:trace.http.request.hits{{service:{service_name}}}",
            "latency_p99": f"p99:trace.http.request.duration{{service:{service_name}}}",
        }

        headers = {
            "DD-API-KEY": settings.datadog_api_key,
            "DD-APPLICATION-KEY": settings.datadog_app_key,
        }
        base = f"https://api.{settings.datadog_site}"

        results = []
        with httpx.Client(timeout=10) as client:
            for name, query in queries.items():
                resp = client.get(
                    f"{base}/api/v1/query",
                    headers=headers,
                    params={"query": query, "from": start, "to": now},
                )
                data = resp.json()
                series = data.get("series", [])
                if series and series[0].get("pointlist"):
                    val = series[0]["pointlist"][-1][1]
                    results.append(f"  {name}: {val:.3f}")
                else:
                    results.append(f"  {name}: no data")

        return f"Datadog metrics for '{service_name}' (last 30min):\n" + "\n".join(results)

    except Exception as e:
        return f"Datadog query failed: {e}"


@tool("Query New Relic Metrics")
def query_newrelic_metrics(service_name: str) -> str:
    """Query New Relic for service error rate and throughput.
    Input: service/application name."""
    try:
        nrql = (
            f"SELECT count(*) as requests, "
            f"filter(count(*), WHERE error IS true) as errors, "
            f"average(duration) as avg_duration "
            f"FROM Transaction WHERE appName = '{service_name}' "
            f"SINCE 30 minutes ago"
        )
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"https://api.newrelic.com/graphql",
                headers={
                    "API-Key": settings.newrelic_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": f"""{{
                        actor {{
                            account(id: {settings.newrelic_account_id}) {{
                                nrql(query: "{nrql}") {{
                                    results
                                }}
                            }}
                        }}
                    }}"""
                },
            )
            data = resp.json()
            results = (
                data.get("data", {})
                .get("actor", {})
                .get("account", {})
                .get("nrql", {})
                .get("results", [{}])
            )
            if not results:
                return f"No New Relic data for '{service_name}'."

            r = results[0]
            return (
                f"New Relic metrics for '{service_name}' (last 30min):\n"
                f"  requests: {r.get('requests', 'N/A')}\n"
                f"  errors: {r.get('errors', 'N/A')}\n"
                f"  avg_duration: {r.get('avg_duration', 'N/A'):.3f}s"
            )

    except Exception as e:
        return f"New Relic query failed: {e}"


# ══════════════════════════════════════════════════════════════
# DIAGNOSER TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Get Recent Deploys from GitHub")
def get_recent_deploys(repo_or_service: str) -> str:
    """Get recent deployments/merges for a repo or service.
    Input should be a repo name (e.g., 'payment-service') or full 'org/repo'."""
    try:
        repo = repo_or_service
        if "/" not in repo and settings.github_org:
            repo = f"{settings.github_org}/{repo_or_service}"

        with httpx.Client(timeout=10) as client:
            # Get recent merged PRs (proxy for deploys)
            resp = client.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers={
                    "Authorization": f"Bearer {settings.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 5},
            )
            prs = resp.json()

            if not prs or isinstance(prs, dict):
                return f"No recent PRs found for '{repo}'. Check repo name."

            lines = []
            for pr in prs:
                if pr.get("merged_at"):
                    lines.append(
                        f"  PR #{pr['number']}: {pr['title']}\n"
                        f"    Author: {pr['user']['login']}\n"
                        f"    Merged: {pr['merged_at']}\n"
                        f"    Changed files: {pr.get('changed_files', '?')}"
                    )
            if not lines:
                return f"No recently merged PRs for '{repo}'."

            return f"Recent deploys for '{repo}':\n" + "\n".join(lines)

    except Exception as e:
        return f"GitHub query failed: {e}"


@tool("Get Pull Request Diff")
def get_pr_diff(repo_and_pr_number: str) -> str:
    """Get the diff/changes from a specific PR. Input should be 'repo#number'
    like 'payment-service#891' or 'org/payment-service#891'."""
    try:
        parts = repo_and_pr_number.split("#")
        if len(parts) != 2:
            return "Input must be 'repo#number', e.g., 'payment-service#891'"

        repo, pr_num = parts[0].strip(), parts[1].strip()
        if "/" not in repo and settings.github_org:
            repo = f"{settings.github_org}/{repo}"

        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_num}/files",
                headers={
                    "Authorization": f"Bearer {settings.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            files = resp.json()

            if not files or isinstance(files, dict):
                return f"Could not fetch PR #{pr_num} from '{repo}'."

            lines = []
            for f in files[:10]:
                patch_preview = (f.get("patch", "")[:300] + "...") if f.get("patch") else "binary"
                lines.append(
                    f"  {f['filename']} (+{f['additions']} -{f['deletions']})\n"
                    f"    {patch_preview}"
                )
            return f"PR #{pr_num} changes:\n" + "\n".join(lines)

    except Exception as e:
        return f"GitHub diff fetch failed: {e}"


def _chroma_client():
    import chromadb
    import os
    os.makedirs(settings.chroma_path, exist_ok=True)
    return chromadb.PersistentClient(path=settings.chroma_path)


@tool("Search Past Incidents")
def search_past_incidents(query: str) -> str:
    """Search past incidents and postmortems for similar patterns.
    Input should describe the symptoms, e.g., 'payment-service high error rate 500'."""
    try:
        client = _chroma_client()

        try:
            collection = client.get_collection("incidents")
        except Exception:
            return "No past incidents in knowledge base yet. Pagemenot will learn as you use it."

        results = collection.query(query_texts=[query], n_results=5)

        if not results["documents"] or not results["documents"][0]:
            return "No similar past incidents found."

        lines = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            lines.append(
                f"  📜 {meta.get('title', 'Untitled')} ({meta.get('date', '?')})\n"
                f"    Root cause: {meta.get('root_cause', 'Unknown')}\n"
                f"    Resolution: {meta.get('resolution', 'Unknown')}\n"
                f"    Excerpt: {doc[:150]}..."
            )
        return f"Similar past incidents:\n" + "\n".join(lines)

    except Exception as e:
        return f"Incident search failed: {e}"


# ══════════════════════════════════════════════════════════════
# REMEDIATOR TOOLS
# ══════════════════════════════════════════════════════════════

@tool("Search Runbooks")
def search_runbooks(query: str) -> str:
    """Search operational runbooks for fix procedures.
    Input should describe the problem, e.g., 'payment-service rollback procedure'."""
    try:
        client = _chroma_client()
        try:
            collection = client.get_collection("runbooks")
        except Exception:
            return (
                "No runbooks in knowledge base yet. "
                "Add markdown files to ./knowledge/runbooks/ and restart."
            )

        results = collection.query(query_texts=[query], n_results=3)

        if not results["documents"] or not results["documents"][0]:
            return "No matching runbooks found."

        lines = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            lines.append(
                f"  📘 {meta.get('title', 'Untitled Runbook')}\n"
                f"    Service: {meta.get('service', 'General')}\n"
                f"    Steps:\n    {doc[:300]}..."
            )
        return f"Matching runbooks:\n" + "\n".join(lines)

    except Exception as e:
        return f"Runbook search failed: {e}"


@tool("Request Human Approval")
def request_human_approval(action_description: str) -> str:
    """Flag an action that needs human approval before execution.
    Input should describe the action, e.g., 'Rollback payment-service to deploy #4520'.
    This will be posted to Slack for engineer approval."""
    # This is a marker — actual approval happens in the Slack layer.
    # The agent's output with [NEEDS APPROVAL] tags triggers the Slack
    # approval flow in pagemenot/slack/interactions.py
    return (
        f"⚠️ HUMAN APPROVAL REQUIRED:\n"
        f"  Action: {action_description}\n"
        f"  Status: Awaiting engineer approval in Slack.\n"
        f"  This action will NOT be executed automatically."
    )


@tool("Kubernetes Rollback")
def kubectl_rollback(deployment_name: str) -> str:
    """Roll back a Kubernetes deployment to the previous revision.
    Input should be 'namespace/deployment' like 'production/payment-service'.
    IMPORTANT: This requires human approval first!"""
    # In a real implementation, this would use the kubernetes client.
    # For safety, it always returns the COMMAND rather than executing it.
    parts = deployment_name.split("/")
    if len(parts) == 2:
        ns, deploy = parts
    else:
        ns, deploy = "default", deployment_name

    return (
        f"🔄 Rollback command prepared (NOT YET EXECUTED):\n"
        f"  kubectl rollout undo deployment/{deploy} -n {ns}\n\n"
        f"  To execute: Engineer must approve via Slack reaction.\n"
        f"  Current status: AWAITING APPROVAL"
    )
