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
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import httpx
from crewai.tools import tool

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.tools")

# Set by triage before crew kickoff so search_runbooks can filter by cloud provider
_triage_cloud_provider: ContextVar[list[str]] = ContextVar("_triage_cloud_provider", default=[])

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")
_GCLOUD_SSH_NOISE = re.compile(
    r"Updating project ssh metadata[^\n]*\n?\.?failed\.?\n?", re.IGNORECASE
)


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

    import os as _os

    _in_cluster = bool(_os.environ.get("KUBERNETES_SERVICE_HOST"))
    _kubeconfig_ok = settings.kubeconfig_path and _os.path.isfile(settings.kubeconfig_path)
    if _in_cluster or _kubeconfig_ok:
        remediator_tools.append(kubectl_rollback)
        _k8s_mode = (
            "in-cluster service account"
            if _in_cluster
            else f"kubeconfig={settings.kubeconfig_path}"
        )
        logger.info(f"✅ Kubernetes connected ({_k8s_mode})")
    elif settings.kubeconfig_path:
        logger.warning(
            f"KUBECONFIG_PATH={settings.kubeconfig_path!r} is not a valid file — kubectl disabled. "
            "Set KUBECONFIG_PATH to a kubeconfig file, or run pagemenot as a pod with a ServiceAccount."
        )

    unconfigured = [
        v
        for v, s in [
            ("PROMETHEUS_URL", settings.prometheus_url),
            ("DATADOG_API_KEY", settings.datadog_api_key),
            ("NEWRELIC_API_KEY", settings.newrelic_api_key),
            ("LOKI_URL", settings.loki_url),
            ("GRAFANA_URL", settings.grafana_url),
            ("PAGERDUTY_API_KEY", settings.pagerduty_api_key),
            ("OPSGENIE_API_KEY", settings.opsgenie_api_key),
            ("GITHUB_TOKEN", settings.github_token),
        ]
        if not s
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
                f"histogram_quantile(0.99, "
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
        with httpx.Client(timeout=settings.pagemenot_http_timeout, headers=headers) as client:
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

        with httpx.Client(timeout=settings.pagemenot_http_timeout, headers=headers) as client:
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
        keywords = keywords.replace('"', "").replace("'", "")[:100]
        logql = f'{{app="{service}"}} |= "{keywords}"'

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=30)

        headers = {}
        if settings.loki_auth_token:
            headers["Authorization"] = f"Bearer {settings.loki_auth_token}"
        if settings.loki_org_id:
            headers["X-Scope-OrgID"] = settings.loki_org_id

        with httpx.Client(timeout=settings.pagemenot_http_timeout, headers=headers) as client:
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

        _warn_err = re.compile(
            r"\b(warn|warning|error|err|fatal|critical|exception|traceback|panic)\b", re.IGNORECASE
        )
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
        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
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
        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
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
                params={
                    "query": alert_id_or_service,
                    "limit": 5,
                    "sort": "createdAt",
                    "order": "desc",
                },
            )
            alerts = resp.json().get("data", [])
            if not alerts:
                return f"No OpsGenie alerts found for '{alert_id_or_service}'."

            lines = []
            for a in alerts:
                lines.append(
                    f"  [{a['id'][:8]}] {a.get('message', '?')} — {a.get('status', '?')} ({a.get('priority', '?')})"
                )
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
        headers = {
            k: v
            for k, v in {
                "DD-API-KEY": settings.datadog_api_key,
                "DD-APPLICATION-KEY": settings.datadog_app_key,
            }.items()
            if v is not None
        }
        base = f"https://api.{settings.datadog_site}"

        results = []
        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
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
        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
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
            avg = r.get("avg_duration")
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


@tool("Get Recent Deploys from GitHub")
def get_recent_deploys(repo_or_service: str) -> str:
    """Get recent deployments/merges for a repo or service.
    Input should be a repo name (e.g., 'payment-service') or full 'org/repo'."""
    try:
        repo = repo_or_service
        if "/" not in repo and settings.github_org:
            repo = f"{settings.github_org}/{repo_or_service}"

        gh_headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
            # Get recent merged PRs (proxy for deploys)
            resp = client.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=gh_headers,
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
                        f"    Merged: {pr['merged_at']}"
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

        with httpx.Client(timeout=settings.pagemenot_http_timeout) as client:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_num}/files",
                headers={
                    "Authorization": f"Bearer {settings.github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            files = resp.json()

            if not files or isinstance(files, dict):
                return f"Could not fetch PR #{pr_num} from '{repo}'."

            lines = []
            for f in files[:10]:
                patch_preview = (f.get("patch", "")[:300] + "...") if f.get("patch") else "binary"
                lines.append(
                    f"  {f['filename']} (+{f['additions']} -{f['deletions']})\n    {patch_preview}"
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
            collection = client.get_or_create_collection(
                settings.chroma_incidents_collection, metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            return "No past incidents in knowledge base yet. Pagemenot will learn as you use it."

        results = collection.query(
            query_texts=[query], n_results=settings.pagemenot_rag_incidents_n_results
        )

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
        return "Similar past incidents:\n" + "\n".join(lines)

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
            collection = client.get_or_create_collection(
                settings.chroma_runbooks_collection, metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            return (
                "No runbooks in knowledge base yet. "
                "Add markdown files to ./knowledge/runbooks/ and restart."
            )

        cloud_providers = _triage_cloud_provider.get()
        where = None
        _specific = [
            p for p in cloud_providers if p in {"gcp", "aws", "k8s", "azure", "onprem", "hetzner"}
        ]
        if _specific:
            _conds = [{"is_generic": {"$eq": 1}}] + [{f"is_{p}": {"$eq": 1}} for p in _specific]
            where = {"$or": _conds}

        results = collection.query(
            query_texts=[query],
            n_results=settings.pagemenot_rag_runbooks_n_results,
            where=where,
        )

        if not results["documents"] or not results["documents"][0]:
            return "No matching runbooks found."

        lines = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            lines.append(
                f"  📘 {meta.get('title', 'Untitled Runbook')}\n"
                f"    Service: {meta.get('service', 'General')}\n"
                f"    Steps:\n    {doc[:300]}..."
            )
        return "Matching runbooks:\n" + "\n".join(lines)

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
# Only runs when PAGEMENOT_EXEC_ENABLED=true
# No destructive operations — only safe/reversible actions
# ══════════════════════════════════════════════════════════════


def _exec_enabled():
    if not settings.pagemenot_exec_enabled and not settings.pagemenot_exec_dry_run:
        raise RuntimeError("PAGEMENOT_EXEC_ENABLED is false — autonomous execution is disabled")


def exec_kubectl(command: str) -> str:
    """Execute a kubectl command from a runbook exec tag.

    Config resolution order (matches kubectl default):
    1. KUBECONFIG_PATH env var → explicit file path
    2. In-cluster service account → automatic when KUBERNETES_SERVICE_HOST is set
    3. ~/.kube/config → local dev fallback
    """
    _exec_enabled()
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would execute: kubectl {command}"

    parts = shlex.split(command)
    kubeconfig = settings.kubeconfig_path

    # Validate kubeconfig path is a file, not a directory (Docker creates dirs for missing mounts)
    if kubeconfig:
        import os as _os

        if not _os.path.isfile(kubeconfig):
            logger.warning(
                f"KUBECONFIG_PATH={kubeconfig!r} is not a file — falling back to default config discovery"
            )
            kubeconfig = None

    if kubeconfig:
        cmd = ["kubectl", "--kubeconfig", kubeconfig] + parts
    else:
        # In-cluster (KUBERNETES_SERVICE_HOST set) or ~/.kube/config — kubectl handles it
        cmd = ["kubectl"] + parts

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=settings.pagemenot_subprocess_timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl failed: {result.stderr[:300]}")
    return result.stdout.strip()[:500]


class ExecSkipped(RuntimeError):
    """Raised when an exec step is skipped due to missing cloud credentials/config."""


def exec_aws(service: str, action: str, params: dict) -> str:
    """Execute an AWS operation.

    Credential order:
    1. AWS_ROLE_ARN set → assume that role via STS (cross-account or least-privilege)
    2. No role → boto3 default chain: instance profile (EC2/ECS), IRSA (EKS),
       AWS_ACCESS_KEY_ID env vars, or ~/.aws/credentials
    """
    _exec_enabled()
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would call: aws {service} {action}({params})"

    import boto3
    import botocore.exceptions

    if not settings.aws_region:
        raise ExecSkipped("AWS not configured on this instance — skipped")

    if settings.aws_role_arn:
        try:
            sts = boto3.client("sts", region_name=settings.aws_region)
            creds = sts.assume_role(
                RoleArn=settings.aws_role_arn,
                RoleSessionName="pagemenot-exec",
            )["Credentials"]
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            raise RuntimeError(f"STS assume_role failed ({code}): {e.response['Error']['Message']}")
        client = boto3.client(
            service,
            region_name=settings.aws_region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    else:
        client = boto3.client(service, region_name=settings.aws_region)

    method = getattr(client, action, None)
    if method is None:
        raise RuntimeError(f"Unknown AWS action '{action}' on service '{service}'")

    # Remap snake_case CLI params → exact boto3 param names via service model
    # Also coerce types: list-type params wrapped in list, integer/boolean params cast
    try:
        op_name = "".join(w.capitalize() for w in action.split("_"))
        # Case-insensitive lookup handles abbreviations like DB→Db, LB→Lb, etc.
        _all_ops = {k.lower(): k for k in client.meta.service_model.operation_names}
        op_name = _all_ops.get(op_name.lower(), op_name)
        members = client.meta.service_model.operation_model(op_name).input_shape.members
        lower_map = {k.lower().replace("_", ""): k for k in members}
        params = {lower_map.get(k.lower().replace("_", ""), k): v for k, v in params.items()}
        for pname, pval in list(params.items()):
            shape = members.get(pname)
            if shape is None:
                continue
            if shape.type_name == "list" and isinstance(pval, str):
                params[pname] = [pval]
            elif shape.type_name == "integer" and isinstance(pval, str):
                try:
                    params[pname] = int(pval)
                except ValueError:
                    pass
            elif shape.type_name == "boolean" and isinstance(pval, str):
                params[pname] = pval.lower() not in ("false", "0", "")
    except Exception:
        pass  # fall through with raw params; boto3 will surface any name errors

    # Pagination (Fix 3): use boto3 paginator when available; cap at 500 items
    try:
        paginator = client.get_paginator(action)
        full = paginator.paginate(**params, PaginationConfig={"MaxItems": 500}).build_full_result()
        return str(full)[:2000]
    except botocore.exceptions.OperationNotPageableError:
        pass  # not pageable — fall through to single call

    try:
        response = method(**params)
    except botocore.exceptions.NoCredentialsError:
        raise RuntimeError(
            "No AWS credentials found. Options: set AWS_ROLE_ARN, attach an instance profile "
            "(EC2/ECS), use IRSA (EKS), or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY."
        )
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
            raise RuntimeError(f"AWS permission denied ({code}): {msg}")
        # Lambda update_alias: alias doesn't exist yet → create it.
        # Only fall back when the alias itself is not found (not the function or version).
        if (
            code == "ResourceNotFoundException"
            and action == "update_alias"
            and ":alias/" in msg
            or "Alias not found" in msg
        ):
            create_method = getattr(client, "create_alias", None)
            if create_method:
                try:
                    response = create_method(**params)
                    return str(response)[:2000]
                except botocore.exceptions.ClientError as ce:
                    raise RuntimeError(
                        f"AWS error ({ce.response['Error']['Code']}): {ce.response['Error']['Message']}"
                    )
        raise RuntimeError(f"AWS error ({code}): {msg}")
    return str(response)[:2000]


def exec_shell(command: str) -> str:
    """Execute a shell command from a runbook exec tag.

    Uses shell=True so runbook steps can use &&, ||, pipes, etc.
    Safe: commands come exclusively from operator-owned runbook files (never LLM output),
    and template variables are validated by _safe_service_name() before substitution.
    """
    _exec_enabled()
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would execute: {command}"
    timeout = (
        settings.pagemenot_az_timeout
        if command.lstrip().startswith("az ")
        else settings.pagemenot_subprocess_timeout
    )
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError(f"Command failed: {detail[:300]}")
    stdout = result.stdout.strip()
    stderr = _GCLOUD_SSH_NOISE.sub("", result.stderr).strip()
    return (stdout or stderr or "ok")[:500]


def exec_http(method: str, url: str, headers: dict | None = None, body: dict | None = None) -> str:
    """Make an HTTP call (health check or alert acknowledge).
    Restricted to domains explicitly configured in .env to prevent SSRF."""
    _exec_enabled()
    if settings.pagemenot_exec_dry_run:
        return f"[DRY RUN] would {method.upper()} {url}"

    # SSRF guard — only allow calls to configured integration domains
    from urllib.parse import urlparse

    allowed_hosts = {
        urlparse(u).hostname
        for u in [
            settings.prometheus_url,
            settings.grafana_url,
            settings.loki_url,
        ]
        if u
    }
    host = urlparse(url).hostname
    if not host or host not in allowed_hosts:
        raise ValueError(
            f"exec_http blocked: '{host}' not in configured integration hosts. "
            f"Only explicitly configured service URLs are allowed."
        )

    with httpx.Client(timeout=settings.pagemenot_http_timeout, verify=True) as client:
        resp = client.request(method.upper(), url, headers=headers or {}, json=body)
        return f"{resp.status_code}: {resp.text[:200]}"


def _resolve_lambda_version(service: str) -> str:
    """Resolve rollback version for a Lambda function.

    Priority:
    1. Current target of the 'stable' alias (confirms/resets alias to known-good state)
    2. Highest published numeric version minus 1 (previous version before latest deployment)
    3. Highest published numeric version if only one exists
    """
    import boto3

    if not settings.aws_region:
        raise ExecSkipped("AWS not configured on this instance — skipped")
    client = boto3.client("lambda", region_name=settings.aws_region)

    # Prefer stable alias target — it was set to a known-good version
    try:
        alias = client.get_alias(FunctionName=service, Name="stable")
        return alias["FunctionVersion"]
    except client.exceptions.ResourceNotFoundException:
        pass

    # No stable alias — fall back to highest-1 (previous version before latest deployment)
    response = client.list_versions_by_function(FunctionName=service)
    versions = sorted(
        [int(v["Version"]) for v in response.get("Versions", []) if v["Version"] != "$LATEST"]
    )
    if not versions:
        raise RuntimeError(f"No published numeric versions found for Lambda {service!r}")
    # Roll back to previous version; if only one version, use it
    target = versions[-2] if len(versions) >= 2 else versions[-1]
    return str(target)


_SELF_INSTANCE_ID: "str | None" = None
_SELF_INSTANCE_ID_FETCHED = False


def _self_instance_id() -> "str | None":
    """Return this host's EC2 instance ID from instance metadata, or None if not on EC2."""
    global _SELF_INSTANCE_ID, _SELF_INSTANCE_ID_FETCHED
    if _SELF_INSTANCE_ID_FETCHED:
        return _SELF_INSTANCE_ID
    _SELF_INSTANCE_ID_FETCHED = True
    try:
        import urllib.request as _ur

        with _ur.urlopen("http://169.254.169.254/latest/meta-data/instance-id", timeout=1) as _r:
            _SELF_INSTANCE_ID = _r.read().decode().strip()
    except Exception:
        pass
    return _SELF_INSTANCE_ID


def _parse_shorthand(s: str) -> "dict | None":
    """Parse AWS CLI shorthand 'Name=X,Value=Y' → {"Name": "X", "Value": "Y"} or None."""
    import re as _re

    if not _re.match(r"^\w+=", s):
        return None
    parts = _re.split(r",(?=\w+=)", s)
    result = {}
    for part in parts:
        if "=" not in part:
            return None
        k, _, v = part.partition("=")
        if not _re.fullmatch(r"[\w\-]+", k):
            return None
        result[k] = v
    return result if result else None


def _safe_service_name(service: str) -> str:
    """Validate service name used in template substitution — only safe chars allowed."""
    if not re.fullmatch(r"[a-zA-Z0-9_\-\.]+", service):
        raise ValueError(f"Unsafe service name for template substitution: {service!r}")
    return service


def dispatch_exec_step(step: str, service: str = "") -> str:
    """Parse and route a single exec step from a runbook to the correct executor.

    Accepts both <!-- exec: command --> (auto-safe) and <!-- exec:approve: command --> (risky).
    Template substitution ({{ service }}) happens after routing and validation.
    """
    # Match both <!-- exec: --> and <!-- exec:approve: --> — raw LLM text rejected
    match = re.match(r"<!--\s*exec(?::approve)?:\s*(.+?)\s*-->", step)
    if not match:
        raise ValueError(
            "Only <!-- exec: --> tagged steps from runbooks are allowed for autonomous execution"
        )
    cmd = match.group(1).strip()

    if not cmd:
        raise ValueError("Empty exec step")

    # Substitute template variables — always sanitize service name to prevent injection
    safe_service = _safe_service_name(service) if service else ""

    # Safety: never execute remediation against the instance pagemenot itself runs on
    _host_id = _self_instance_id()
    if _host_id and safe_service and safe_service == _host_id:
        raise RuntimeError(
            f"Execution blocked: target '{safe_service}' is the pagemenot host instance. "
            "Deploy pagemenot on a separate host or behind a load balancer."
        )
    ns_map = {
        k: v
        for pair in settings.pagemenot_service_namespaces.split(",")
        if "=" in pair
        for k, v in [pair.strip().split("=", 1)]
    }
    namespace = (
        ns_map.get(service, settings.pagemenot_exec_namespace)
        if service
        else settings.pagemenot_exec_namespace
    )
    # Resolve {{ lambda_version }} lazily — only if needed to avoid extra API calls
    _lambda_version: str | None = None

    def _get_lambda_version() -> str:
        nonlocal _lambda_version
        if _lambda_version is None:
            _lambda_version = _resolve_lambda_version(safe_service)
        return _lambda_version

    rg = settings.azure_resource_group or ""
    for _raw, _sub in [
        ("{{ service }}", safe_service),
        ("{{service}}", safe_service),
        ("{{ namespace }}", namespace),
        ("{{namespace}}", namespace),
        ("{{ resource_group }}", rg),
        ("{{resource_group}}", rg),
    ]:
        cmd = cmd.replace(_raw, _sub)

    # Dynamic template vars resolved on demand
    if "{{ lambda_version }}" in cmd or "{{lambda_version}}" in cmd:
        lv = _get_lambda_version()
        cmd = cmd.replace("{{ lambda_version }}", lv).replace("{{lambda_version}}", lv)

    # Route to correct executor
    if cmd.startswith("kubectl "):
        return exec_kubectl(cmd[len("kubectl ") :])
    elif cmd.startswith("aws "):
        import json as _json
        import botocore.session as _bcs

        # Strip pipes — boto3 handles response natively
        pipe_idx = cmd.find(" | ")
        cmd_clean = cmd[:pipe_idx].strip() if pipe_idx != -1 else cmd
        parts = shlex.split(cmd_clean)
        if len(parts) < 3:
            raise ValueError(f"Invalid AWS command: {cmd!r}")
        aws_service, aws_action = parts[1], parts[2].replace("-", "_")

        # CLI-only flags — no boto3 equivalent
        _CLI_ONLY = {
            "region",
            "output",
            "query",
            "profile",
            "no_sign_request",
            "endpoint_url",
            "color",
            "no_paginate",
            "debug",
            "cli_connect_timeout",
            "cli_read_timeout",
            "cli_binary_format",
            "ca_bundle",
            "no_verify_ssl",
            "no_cli_pager",
        }
        _REMAP = {"max_items": "limit"}
        _INT_PARAMS = {"limit", "max_results", "max_items", "count", "duration_seconds"}

        # Load valid flag names (no-creds botocore session) to distinguish flags from
        # values that happen to start with "--" (Fix 2)
        _valid_flags: frozenset[str] = frozenset()
        try:
            _op_name = "".join(w.capitalize() for w in aws_action.split("_"))
            _members = (
                _bcs.Session()
                .get_service_model(aws_service)
                .operation_model(_op_name)
                .input_shape.members
            )
            _valid_flags = frozenset(k.lower().replace("_", "") for k in _members)
        except Exception:
            pass  # fall back: all "--" tokens treated as flags

        params: dict = {}
        i = 3
        while i < len(parts):
            token = parts[i]
            if not token.startswith("--"):
                i += 1
                continue
            snake = token.lstrip("-").replace("-", "_")

            # Collect values: advance j while next token is not a recognised flag (Fix 1 + 2)
            values: list[str] = []
            j = i + 1
            while j < len(parts):
                nxt = parts[j]
                if nxt.startswith("--"):
                    nxt_norm = nxt.lstrip("-").replace("-", "_").replace("_", "")
                    nxt_snake = nxt.lstrip("-").replace("-", "_")
                    # Stop if it's a recognised API flag or a CLI-only flag
                    if nxt_norm in _valid_flags or nxt_snake in _CLI_ONLY:
                        break
                    # Unknown "--xxx" → treat as value (Fix 2)
                values.append(nxt)
                j += 1

            if snake in _CLI_ONLY:
                i = j
                continue
            snake = _REMAP.get(snake, snake)

            if not values:
                params[snake] = True  # boolean switch
            elif len(values) == 1:
                raw = values[0]
                # JSON/complex params: try to parse "[…]" or "{…}" (Fix 4)
                if raw[:1] in ("[", "{"):
                    try:
                        params[snake] = _json.loads(raw)
                    except _json.JSONDecodeError:
                        params[snake] = raw
                elif snake in _INT_PARAMS:
                    try:
                        params[snake] = int(raw)
                    except ValueError:
                        raise ValueError(f"Parameter {snake} must be an integer, got {raw!r}")
                else:
                    # AWS CLI shorthand: Name=X,Value=Y → [{"Name": "X", "Value": "Y"}]
                    shorthand = _parse_shorthand(raw)
                    params[snake] = [shorthand] if shorthand is not None else raw
            else:
                # Multi-value list (Fix 1): e.g. --log-stream-names s1 s2 s3
                result_list: list = []
                for v in values:
                    if v[:1] in ("[", "{"):
                        try:
                            result_list.append(_json.loads(v))
                            continue
                        except _json.JSONDecodeError:
                            pass
                    shorthand = _parse_shorthand(v)
                    result_list.append(shorthand if shorthand is not None else v)
                params[snake] = result_list
            i = j
        return exec_aws(aws_service, aws_action, params)
    elif cmd.startswith("http://") or cmd.startswith("https://"):
        return exec_http("GET", cmd)
    else:
        return exec_shell(cmd)


def get_runbook_exec_steps(
    query: str, service: str = "", cloud_providers: list[str] | None = None
) -> dict[str, list[tuple[str, str]]]:
    """Search runbooks by query, return exec steps split by approval requirement.

    Returns {"auto": [(tag, filename), ...], "approve": [(tag, filename), ...]}
      - auto: <!-- exec: cmd --> steps — run immediately, no human needed
      - approve: <!-- exec:approve: cmd --> steps — always queued for human approval
    """
    try:
        client = _chroma_client()
        collection = client.get_or_create_collection(
            settings.chroma_runbooks_collection, metadata={"hnsw:space": "cosine"}
        )

        where = None
        _specific = [
            p
            for p in (cloud_providers or [])
            if p in {"gcp", "aws", "k8s", "azure", "onprem", "hetzner"}
        ]
        if _specific:
            _conds = [{"is_generic": {"$eq": 1}}] + [{f"is_{p}": {"$eq": 1}} for p in _specific]
            where = {"$or": _conds}

        results = collection.query(
            query_texts=[query],
            n_results=settings.pagemenot_rag_runbooks_n_results,
            where=where,
        )
        if not results["documents"] or not results["documents"][0]:
            return {"auto": [], "approve": []}

        from pagemenot.rag import RUNBOOKS_DIR

        auto_steps: list[tuple[str, str]] = []
        approve_steps: list[tuple[str, str]] = []
        seen: set[str] = set()
        for meta in results["metadatas"][0]:
            filename = meta.get("filename", "")
            if not filename or filename in seen:
                continue
            seen.add(filename)
            _matches = list(RUNBOOKS_DIR.glob(f"**/{filename}"))
            if not _matches:
                continue
            content = _matches[0].read_text(encoding="utf-8")
            for match in re.finditer(r"<!--\s*exec(?::approve)?:\s*.+?\s*-->", content):
                tag = match.group(0)
                if re.match(r"<!--\s*exec:approve:", tag):
                    approve_steps.append((tag, filename))
                else:
                    auto_steps.append((tag, filename))

        return {"auto": auto_steps, "approve": approve_steps}

    except Exception as e:
        logger.warning(f"Runbook exec step lookup failed: {e}")
        return {"auto": [], "approve": []}
