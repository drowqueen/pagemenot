"""
Auto-discovery of tools based on what's configured in .env.

This is the core of the "zero config" experience:
- Team adds PROMETHEUS_URL to .env → MonitorAgent gets Prometheus tool
- Team adds GITHUB_TOKEN → DiagnoserAgent gets GitHub deploy history tool
- No tool config? Agents still work with whatever IS available

Each tool is a CrewAI @tool that wraps the actual API call.
"""

import logging
import re
import shlex
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from crewai.tools import tool

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.tools")

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_.\-]+$')


def _safe_name(name: str) -> str:
    """Validate that a name contains only safe characters for use in queries.
    Returns the name unchanged, raises ValueError if unsafe."""
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"Unsafe characters in name: {name!r}")
    return name


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
        try:
            service_name = _safe_name(service_name)
        except ValueError as e:
            return f"Invalid service name: {e}"

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
    """Get currently firing Grafana alerts related to a service.
    Input should be the service name."""
    try:
        headers = {"Authorization": f"Bearer {settings.grafana_api_key}"}
        if settings.grafana_org_id:
            headers["X-Grafana-Org-Id"] = settings.grafana_org_id

        with httpx.Client(timeout=10, headers=headers) as client:
            # Query active firing alerts via Grafana-managed Alertmanager API
            resp = client.get(
                f"{settings.grafana_url}/api/alertmanager/grafana/api/v2/alerts",
                params={"active": "true", "silenced": "false", "inhibited": "false"},
            )
            resp.raise_for_status()
            alerts = resp.json()

            relevant = [a for a in alerts if service_name.lower() in str(a).lower()]
            if not relevant:
                return f"No active Grafana alerts found for '{service_name}'."

            summaries = []
            for a in relevant[:5]:
                labels = a.get("labels", {})
                annotations = a.get("annotations", {})
                summaries.append(
                    f"  - {labels.get('alertname', 'Unknown')}: "
                    f"{annotations.get('summary', a.get('status', {}).get('state', 'N/A'))}"
                )
            return f"Active Grafana alerts for '{service_name}':\n" + "\n".join(summaries)

    except Exception as e:
        return f"Grafana query failed: {e}"


@tool("Search Logs in Loki")
def search_logs_loki(query: str) -> str:
    """Search Loki for log entries matching a query.
    Input should be a LogQL query or a service name with keywords
    like 'payment-service error' or '{app="checkout"} |= "exception"'."""
    try:
        # Never accept raw LogQL from alert input — always build from validated parts
        parts = query.split(maxsplit=1)
        service = parts[0]
        keywords = parts[1] if len(parts) > 1 else "error"
        try:
            service = _safe_name(service)
        except ValueError as e:
            return f"Invalid service name: {e}"
        # keywords: strip quotes to prevent LogQL injection
        keywords = keywords.replace('"', '').replace("'", '')[:100]
        logql = f'{{app="{service}"}} |= "{keywords}"'

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

        _warn_err = re.compile(r'\b(warn|warning|error|err|fatal|critical|exception|traceback|panic)\b', re.IGNORECASE)
        lines = []
        for stream in streams[:5]:
            for ts, line in stream.get("values", [])[:50]:
                if _warn_err.search(line):
                    lines.append(f"  {line[:200]}")
                if len(lines) >= 20:
                    break

        if not lines:
            return f"No warning/error log entries found (last 30min) for query: {logql}"
        return f"Loki warning/error logs ({len(lines)} entries, last 30min):\n" + "\n".join(lines)

    except Exception as e:
        return f"Loki query failed: {e}"


@tool("Get PagerDuty Incident Details")
def get_pagerduty_incident(incident_id_or_description: str) -> str:
    """Get details about a PagerDuty incident.
    Input can be an incident ID (like P1234567) or a search term."""
    try:
        pd_headers = {
            "Authorization": f"Token token={settings.pagerduty_api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=10) as client:
            # Try as incident ID first
            if incident_id_or_description.startswith("P"):
                resp = client.get(
                    f"https://api.pagerduty.com/incidents/{incident_id_or_description}",
                    headers=pd_headers,
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
                headers=pd_headers,
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
        now = int(time.time())
        start = now - 1800

        queries = {
            "error_rate": f"sum:trace.http.request.errors{{service:{service_name}}}",
            "request_rate": f"sum:trace.http.request.hits{{service:{service_name}}}",
            "latency_p99": f"p99:trace.http.request.duration{{service:{service_name}}}",
        }

        # Filter None values — httpx would send "None" as a string otherwise
        headers = {k: v for k, v in {
            "DD-API-KEY": settings.datadog_api_key,
            "DD-APPLICATION-KEY": settings.datadog_app_key,
        }.items() if v is not None}
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
        if not settings.newrelic_account_id:
            return "New Relic account ID not configured."

        # NRQL has no bind parameters — validate service_name before embedding
        try:
            service_name = _safe_name(service_name)
        except ValueError as e:
            return f"Invalid service name: {e}"
        nrql = (
            "SELECT count(*) as requests, "
            "filter(count(*), WHERE error IS true) as errors, "
            "average(duration) as avg_duration "
            f"FROM Transaction WHERE appName = '{service_name}' "
            "SINCE 30 minutes ago"
        )
        gql = """
            query($accountId: Int!, $nrql: Nrql!) {
                actor {
                    account(id: $accountId) {
                        nrql(query: $nrql) {
                            results
                        }
                    }
                }
            }
        """
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                "https://api.newrelic.com/graphql",
                headers={
                    "API-Key": settings.newrelic_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": gql,
                    "variables": {
                        "accountId": int(settings.newrelic_account_id),
                        "nrql": nrql,
                    },
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
            avg = r.get('avg_duration')
            avg_str = f"{avg:.3f}s" if isinstance(avg, (int, float)) else "N/A"
            return (
                f"New Relic metrics for '{service_name}' (last 30min):\n"
                f"  requests: {r.get('requests', 'N/A')}\n"
                f"  errors: {r.get('errors', 'N/A')}\n"
                f"  avg_duration: {avg_str}"
            )

    except Exception as e:
        return f"New Relic query failed: {e}"


# ══════════════════════════════════════════════════════════════
# DIAGNOSER TOOLS
# ══════════════════════════════════════════════════════════════

_SERVICES_PATH = Path(__file__).parent.parent / "config" / "services.yaml"
_SERVICES_CACHE: dict = {}
_SERVICES_MTIME: float = 0.0


def _load_services() -> dict:
    """Hot-reload config/services.yaml when the file changes."""
    global _SERVICES_CACHE, _SERVICES_MTIME
    if not _SERVICES_PATH.exists():
        return {}
    mtime = _SERVICES_PATH.stat().st_mtime
    if mtime != _SERVICES_MTIME:
        import yaml
        with open(_SERVICES_PATH) as f:
            _SERVICES_CACHE = yaml.safe_load(f) or {}
        _SERVICES_MTIME = mtime
        logger.info("config/services.yaml reloaded")
    return _SERVICES_CACHE


def _resolve_repos(service: str) -> list[tuple[str, list[str]]]:
    """Return [(org/repo, [path_prefixes]), ...] for a service.

    Reads config/services.yaml. Falls back to GITHUB_ORG/service-name.
    """
    org = settings.github_org or ""
    entry = _load_services().get(service)

    if not entry:
        repo = service if "/" in service else f"{org}/{service}" if org else service
        return [(repo, [])]

    repos = entry.get("repos", [])
    path_prefix = entry.get("path_prefix", "")
    paths = [path_prefix] if path_prefix else []
    return [
        (r if "/" in r else f"{org}/{r}", paths)
        for r in repos
    ]


_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _gh_headers() -> dict:
    return {**_GH_HEADERS, "Authorization": f"Bearer {settings.github_token}"}


def _pr_touches_paths(files: list[dict], paths: list[str]) -> bool:
    """Return True if any changed file is under one of the given path prefixes."""
    if not paths:
        return True
    return any(f["filename"].startswith(p) for f in files for p in paths)


@tool("Get Recent Deploys from GitHub")
def get_recent_deploys(service_name: str) -> str:
    """Get recent merged PRs for a service. Input: service name (e.g. 'payment-service').
    Resolves repo(s) via knowledge/services.yaml; falls back to GITHUB_ORG/service-name."""
    try:
        repo_entries = _resolve_repos(service_name)
        all_lines = []

        with httpx.Client(timeout=10) as client:
            for repo, path_prefixes in repo_entries:
                resp = client.get(
                    f"https://api.github.com/repos/{repo}/pulls",
                    headers=_gh_headers(),
                    params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 10},
                )
                if resp.status_code != 200:
                    all_lines.append(f"  [{repo}] API error {resp.status_code}")
                    continue

                prs = resp.json()
                if not prs or isinstance(prs, dict):
                    all_lines.append(f"  [{repo}] No recent PRs found")
                    continue

                for pr in prs:
                    if not pr.get("merged_at"):
                        continue
                    # For monorepos: filter by path prefix using the files endpoint
                    if path_prefixes:
                        files_resp = client.get(
                            f"https://api.github.com/repos/{repo}/pulls/{pr['number']}/files",
                            headers=_gh_headers(),
                        )
                        if files_resp.status_code != 200 or not _pr_touches_paths(files_resp.json(), path_prefixes):
                            continue

                    all_lines.append(
                        f"  [{repo}] PR #{pr['number']}: {pr['title']}\n"
                        f"    Author: {pr['user']['login']}  Merged: {pr['merged_at']}"
                    )

        return (
            f"Recent deploys for '{service_name}':\n" + "\n".join(all_lines)
            if all_lines
            else f"No recent merged PRs found for '{service_name}'."
        )

    except Exception as e:
        return f"GitHub query failed: {e}"


@tool("Get Pull Request Diff")
def get_pr_diff(repo_and_pr_number: str) -> str:
    """Get changed files and diff from a PR. Input: 'repo#number' or 'org/repo#number'."""
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
                headers=_gh_headers(),
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


# ══════════════════════════════════════════════════════════════
# EXECUTOR — plain functions (not @tool), called directly
# Safety gates: PAGEMENOT_EXEC_DRY_RUN (simulate) and
# PAGEMENOT_APPROVAL_GATE ([NEEDS APPROVAL] steps require human click).
# Runbook authors are trusted — only <!-- exec: --> tagged steps run,
# never free-form LLM output.
# ══════════════════════════════════════════════════════════════

_SHELL_WHITELIST = [
    r"^curl\s+-sf\s+https?://\S+/health$",
    r"^curl\s+-sf\s+https?://\S+/ready$",
]

# AWS: read-only actions only for autonomous execution.
_AWS_ALLOWED = {
    "ecs": {"describe_services", "describe_tasks"},
    "cloudwatch": {"get_metric_statistics", "get_metric_data"},
}

# SSM: diagnostic read-only commands only. No package installs, no file writes, no destructive ops.
_SSM_COMMAND_WHITELIST = [
    r"^journalctl\s+-u\s+[\w\-\.]+(\s+--no-pager)?(\s+-n\s+\d+)?(\s+--since\s+[\w\-\s:\"\']+)?$",
    r"^systemctl\s+status\s+[\w\-\.]+$",
    r"^tail\s+-n\s+\d+\s+/var/log/[\w\-\.]+$",
    r"^df\s+-h$",
    r"^free\s+-[mhb]$",
    r"^ps\s+aux$",
    r"^ss\s+-tlnp$",
    r"^curl\s+-sf\s+https?://[a-zA-Z0-9\-\.]+(:\d+)?/(health|ready|status)$",
]


def exec_kubectl(command: str) -> str:
    """Execute a kubectl command from a runbook <!-- exec: --> tag.

    Safety gates: PAGEMENOT_EXEC_DRY_RUN (simulate without running) and
    PAGEMENOT_APPROVAL_GATE (risky steps require human approval before reaching here).
    Runbook authors are trusted — this function is never called with LLM-generated text.
    """
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would execute: kubectl {command}"
    parts = shlex.split(command)
    kubeconfig = settings.kubeconfig_path or os.environ.get("KUBECONFIG")
    cmd = (["kubectl", "--kubeconfig", kubeconfig] if kubeconfig else ["kubectl"]) + parts
    # Add --timeout to rollout status so it doesn't block indefinitely on a stuck deployment
    if parts and parts[0] == "rollout" and len(parts) > 1 and parts[1] == "status" and "--timeout" not in command:
        cmd = cmd + ["--timeout=30s"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        stderr = result.stderr[:300]
        stdout = result.stdout.strip()[:300]
        # kubectl top fails when metrics-server isn't available or pods are not running — diagnostic only, non-fatal
        if parts and parts[0] == "top" and (
            "metrics.k8s.io" in stderr or "Metrics not available" in stderr or "Metrics API" in stderr
        ):
            return f"[WARN] kubectl top unavailable (pods not running or metrics-server not ready): {stderr.strip()}"
        # rollout status non-zero means deployment not progressing — report as status, not exception
        if parts and parts[0] == "rollout" and len(parts) > 1 and parts[1] == "status":
            return f"[WARN] Rollout not healthy: {(stdout or stderr).strip()}"
        raise RuntimeError(f"kubectl failed: {stderr}")
    return result.stdout.strip()[:500]


def exec_aws(service: str, action: str, params: dict) -> str:
    """Execute a safe AWS operation via assumed IAM role."""
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would call: aws {service} {action}({params})"
    if not settings.aws_role_arn:
        raise RuntimeError("AWS_ROLE_ARN not configured")

    allowed = _AWS_ALLOWED.get(service, set())
    if action not in allowed:
        raise ValueError(f"AWS {service}:{action} not in allowed list")

    try:
        import boto3
    except ImportError:
        raise RuntimeError("boto3 not installed — add to requirements.txt")

    sts = boto3.client("sts", region_name=settings.aws_region)
    creds = sts.assume_role(
        RoleArn=settings.aws_role_arn,
        RoleSessionName="pagemenot-exec",
    )["Credentials"]

    client = boto3.client(
        service,
        region_name=settings.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    response = getattr(client, action)(**params)
    return str(response)[:300]


def exec_ssm(instance_id: str, command: str) -> str:
    """Run a whitelisted diagnostic command on an EC2 instance via SSM (no SSH/bastion needed)."""
    if not re.fullmatch(r'i-[0-9a-f]{8,17}', instance_id):
        raise ValueError(f"Invalid EC2 instance ID: {instance_id!r}")
    if not any(re.fullmatch(p, command) for p in _SSM_COMMAND_WHITELIST):
        raise ValueError(f"SSM command not in whitelist: {command!r}")
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would SSM run on {instance_id}: {command}"
    if not settings.aws_role_arn:
        raise RuntimeError("AWS_ROLE_ARN not configured")

    try:
        import boto3, time
    except ImportError:
        raise RuntimeError("boto3 not installed")

    sts = boto3.client("sts", region_name=settings.aws_region)
    creds = sts.assume_role(
        RoleArn=settings.aws_role_arn,
        RoleSessionName="pagemenot-ssm",
    )["Credentials"]
    ssm = boto3.client(
        "ssm", region_name=settings.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )

    cmd_id = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
    )["Command"]["CommandId"]

    # Poll until terminal (timeout 60s)
    for _ in range(12):
        time.sleep(5)
        inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        status = inv["Status"]
        if status == "Success":
            return inv.get("StandardOutputContent", "").strip()[:500]
        if status in ("Failed", "Cancelled", "TimedOut"):
            raise RuntimeError(f"SSM command {status}: {inv.get('StandardErrorContent', '')[:200]}")
    raise RuntimeError("SSM command timed out after 60s")


def exec_azure_run_command(resource_group: str, vm_name: str, command: str) -> str:
    """Run a whitelisted diagnostic command on an Azure VM via Run Command (no SSH/bastion needed)."""
    if not re.fullmatch(r'[\w\-\.]+', resource_group):
        raise ValueError(f"Invalid resource group: {resource_group!r}")
    if not re.fullmatch(r'[\w\-\.]+', vm_name):
        raise ValueError(f"Invalid VM name: {vm_name!r}")
    if not any(re.fullmatch(p, command) for p in _SSM_COMMAND_WHITELIST):
        raise ValueError(f"Azure Run Command not in whitelist: {command!r}")
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would Azure Run Command on {resource_group}/{vm_name}: {command}"
    if not all([settings.azure_tenant_id, settings.azure_client_id,
                settings.azure_client_secret, settings.azure_subscription_id]):
        raise RuntimeError("Azure credentials not configured (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_SUBSCRIPTION_ID)")

    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.compute.models import RunCommandInput
    except ImportError:
        raise RuntimeError("azure-identity and azure-mgmt-compute not installed")

    credential = ClientSecretCredential(
        tenant_id=settings.azure_tenant_id,
        client_id=settings.azure_client_id,
        client_secret=settings.azure_client_secret,
    )
    client = ComputeManagementClient(credential, settings.azure_subscription_id)
    result = client.virtual_machines.begin_run_command(
        resource_group_name=resource_group,
        vm_name=vm_name,
        parameters=RunCommandInput(command_id="RunShellScript", script=[command]),
    ).result(timeout=60)

    command_output = result.output.strip() if result.output else ""
    command_error = result.error.strip() if result.error else ""
    if result.exit_code != 0:
        raise RuntimeError(f"Azure Run Command failed (exit {result.exit_code}): {command_error[:200]}")
    return command_output[:500]


def exec_shell(command: str) -> str:
    """Execute a whitelisted shell command (read-only health checks only)."""
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would execute: {command}"
    # re.fullmatch — prevents prefix-bypass attacks (e.g. "curl -sf http://x/health; rm -rf /")
    if not any(re.fullmatch(pattern, command) for pattern in _SHELL_WHITELIST):
        raise ValueError(f"Command not in whitelist: {command!r}")
    result = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {result.stderr[:300]}")
    return result.stdout.strip()[:500]


def exec_http(method: str, url: str, headers: dict | None = None, body: dict | None = None) -> str:
    """Make an HTTP call (health check or alert acknowledge).
    Restricted to domains explicitly configured in .env to prevent SSRF."""
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would {method.upper()} {url}"

    # SSRF guard — only allow calls to configured integration domains
    from urllib.parse import urlparse
    allowed_hosts = {
        urlparse(u).hostname
        for u in [
            settings.prometheus_url, settings.grafana_url, settings.loki_url,
        ]
        if u
    }
    host = urlparse(url).hostname
    if not host or host not in allowed_hosts:
        raise ValueError(
            f"exec_http blocked: '{host}' not in configured integration hosts. "
            f"Only explicitly configured service URLs are allowed."
        )

    with httpx.Client(timeout=10, verify=True) as client:
        resp = client.request(method.upper(), url, headers=headers or {}, json=body)
        return f"{resp.status_code}: {resp.text[:200]}"


def _safe_service_name(service: str) -> str:
    """Validate service name used in template substitution — only safe chars allowed."""
    if not re.fullmatch(r'[a-zA-Z0-9_\-]+', service):
        raise ValueError(f"Unsafe service name for template substitution: {service!r}")
    return service


def dispatch_exec_step(step: str, service: str = "") -> str:
    """Parse and route a single exec step from a runbook to the correct executor.

    Only accepts <!-- exec: command --> tags from verified runbook files.
    Template substitution ({{ service }}) happens after routing and validation.
    """
    # Only exec tags from runbook files are accepted — raw LLM text rejected
    match = re.match(r'<!--\s*exec:\s*(.+?)\s*-->', step)
    if not match:
        raise ValueError("Only <!-- exec: --> tagged steps from runbooks are allowed for autonomous execution")
    cmd = match.group(1).strip()

    if not cmd:
        raise ValueError("Empty exec step")

    # Substitute template variables
    from pagemenot.config import settings as _s
    namespace = _s.pagemenot_exec_namespace
    for _raw, _sub in [("{{ service }}", _safe_service_name(service) if service else ""),
                       ("{{service}}", service),
                       ("{{ namespace }}", namespace),
                       ("{{namespace}}", namespace)]:
        cmd = cmd.replace(_raw, _sub)

    # Route to correct executor
    if cmd.startswith("kubectl "):
        kubectl_cmd = cmd[len("kubectl "):]
        return exec_kubectl(kubectl_cmd)
    elif cmd.startswith("ssm:"):
        # Format: ssm:<instance-id> <command>
        rest = cmd[4:]
        parts = rest.split(" ", 1)
        if len(parts) != 2:
            raise ValueError("Invalid SSM step format — expected: ssm:<instance-id> <command>")
        return exec_ssm(parts[0].strip(), parts[1].strip())
    elif cmd.startswith("azure:"):
        # Format: azure:<resource-group>/<vm-name> <command>
        rest = cmd[6:]
        parts = rest.split(" ", 1)
        if len(parts) != 2 or "/" not in parts[0]:
            raise ValueError("Invalid Azure step format — expected: azure:<resource-group>/<vm-name> <command>")
        rg, vm = parts[0].split("/", 1)
        return exec_azure_run_command(rg.strip(), vm.strip(), parts[1].strip())
    elif cmd.startswith("aws "):
        parts = shlex.split(cmd)
        if len(parts) < 3:
            raise ValueError(f"Invalid AWS command: {cmd!r}")
        aws_service, aws_action = parts[1], parts[2].replace("-", "_")
        params: dict = {}
        i = 3
        while i + 1 < len(parts):
            if parts[i].startswith("--"):
                params[parts[i].lstrip("-").replace("-", "_")] = parts[i + 1]
                i += 2
            else:
                i += 1
        return exec_aws(aws_service, aws_action, params)
    elif cmd.startswith("http://") or cmd.startswith("https://"):
        return exec_http("GET", cmd)
    else:
        return exec_shell(cmd)


def get_runbook_exec_steps(query: str, service: str = "") -> list[str]:
    """Search runbooks by query, return all <!-- exec: --> steps from matched files."""
    try:
        client = _chroma_client()
        try:
            collection = client.get_collection("runbooks")
        except Exception:
            return []

        results = collection.query(query_texts=[query], n_results=3)
        if not results["documents"] or not results["documents"][0]:
            return []

        from pagemenot.knowledge.rag import RUNBOOKS_DIR

        # Only the most-relevant runbook executes; multiple runbooks produce conflicting step sequences.
        exec_steps: list[str] = []
        for meta in results["metadatas"][0]:
            filename = meta.get("filename", "")
            if not filename:
                continue
            runbook_path = RUNBOOKS_DIR / filename
            if runbook_path.exists():
                content = runbook_path.read_text(encoding="utf-8")
                for match in re.finditer(r'<!--\s*exec:\s*.+?\s*-->', content):
                    exec_steps.append(match.group(0))
            if exec_steps:
                break

        return exec_steps

    except Exception as e:
        logger.warning(f"Runbook exec step lookup failed: {e}")
        return []
