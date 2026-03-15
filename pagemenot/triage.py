"""
Triage runner — seeds mock context if needed, then runs the crew.

The flow:
1. Alert arrives (webhook or /pagemenot triage)
2. If mock mode: load scenario data into mock tools
3. Build crew with real or mock tools (auto-detected)
4. Run crew → structured result
5. Post to Slack

Teams see none of this. They see: alert → triage → result.
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.triage")
_executor = ThreadPoolExecutor(max_workers=6)

# ── Deduplication store ────────────────────────────────────────
# (service, title_hash) → expiry timestamp (time.monotonic())
# Persisted to file so container restarts don't lose state.
_active_incidents: dict[tuple[str, str], float] = {}
_dedup_lock = threading.Lock()
_DEDUP_FILE = "/app/data/dedup.json"  # fallback when no state bucket configured
_DEDUP_OBJECT = "state/dedup.json"  # object key inside the bucket


def _bucket_read(bucket_url: str, object_key: str = _DEDUP_OBJECT) -> dict:
    """Read JSON object from gs://, s3://, or az:// bucket. Returns {} on miss/error."""
    try:
        if bucket_url.startswith("gs://"):
            from google.cloud import storage as gcs

            bucket_name = bucket_url[5:].rstrip("/")
            client = gcs.Client()
            blob = client.bucket(bucket_name).blob(object_key)
            if not blob.exists():
                return {}
            return json.loads(blob.download_as_text())
        elif bucket_url.startswith("s3://"):
            import boto3

            bucket_name = bucket_url[5:].rstrip("/")
            s3 = boto3.client("s3")
            try:
                obj = s3.get_object(Bucket=bucket_name, Key=object_key)
                return json.loads(obj["Body"].read())
            except s3.exceptions.NoSuchKey:
                return {}
        elif bucket_url.startswith("az://"):
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient

            parts = bucket_url[5:].rstrip("/").split("/", 1)
            account, container = parts[0], parts[1] if len(parts) > 1 else "pagemenot"
            client = BlobServiceClient(
                f"https://{account}.blob.core.windows.net", DefaultAzureCredential()
            )
            blob = client.get_blob_client(container=container, blob=object_key)
            try:
                return json.loads(blob.download_blob().readall())
            except Exception:
                return {}
        else:
            logger.warning("Unsupported state bucket scheme: %s", bucket_url)
            return {}
    except Exception as e:
        logger.warning("Could not read from bucket %s/%s: %s", bucket_url, object_key, e)
        return {}


def _bucket_write(bucket_url: str, data: dict, object_key: str = _DEDUP_OBJECT) -> None:
    """Write JSON object to gs://, s3://, or az:// bucket."""
    try:
        payload = json.dumps(data)
        if bucket_url.startswith("gs://"):
            from google.cloud import storage as gcs

            bucket_name = bucket_url[5:].rstrip("/")
            client = gcs.Client()
            client.bucket(bucket_name).blob(object_key).upload_from_string(
                payload, content_type="application/json"
            )
        elif bucket_url.startswith("s3://"):
            import boto3

            bucket_name = bucket_url[5:].rstrip("/")
            boto3.client("s3").put_object(Bucket=bucket_name, Key=object_key, Body=payload)
        elif bucket_url.startswith("az://"):
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient

            parts = bucket_url[5:].rstrip("/").split("/", 1)
            account, container = parts[0], parts[1] if len(parts) > 1 else "pagemenot"
            client = BlobServiceClient(
                f"https://{account}.blob.core.windows.net", DefaultAzureCredential()
            )
            client.get_blob_client(container=container, blob=object_key).upload_blob(
                payload, overwrite=True, content_settings={"content_type": "application/json"}
            )
        else:
            logger.warning("Unsupported state bucket scheme: %s", bucket_url)
    except Exception as e:
        logger.warning("Could not write to bucket %s/%s: %s", bucket_url, object_key, e)


def _load_dedup() -> None:
    """Load persisted dedup entries on startup, pruning already-expired ones."""
    bucket = settings.pagemenot_state_bucket
    try:
        if bucket:
            raw = _bucket_read(bucket)
        elif os.path.exists(_DEDUP_FILE):
            with open(_DEDUP_FILE) as f:
                raw = json.load(f)
        else:
            return
        now = time.monotonic()
        with _dedup_lock:
            for k, exp in raw.items():
                parts = k.split("\x00", 1)
                if len(parts) == 2 and now < exp:
                    _active_incidents[(parts[0], parts[1])] = exp
        logger.info(
            "Loaded %d dedup entries from %s", len(_active_incidents), bucket or _DEDUP_FILE
        )
    except Exception as e:
        logger.warning("Could not load dedup state: %s", e)


def _save_dedup() -> None:
    """Persist current (non-expired) dedup entries. Called under _dedup_lock."""
    bucket = settings.pagemenot_state_bucket
    try:
        now = time.monotonic()
        serialisable = {
            f"{k[0]}\x00{k[1]}": exp for k, exp in _active_incidents.items() if exp > now
        }
        if bucket:
            _bucket_write(bucket, serialisable)
        else:
            os.makedirs(os.path.dirname(_DEDUP_FILE), exist_ok=True)
            with open(_DEDUP_FILE, "w") as f:
                json.dump(serialisable, f)
    except Exception as e:
        logger.warning("Could not save dedup state: %s", e)


_load_dedup()

# ── Cloud Run URL patterns (uptime_url resource type) ──────────
# Pattern 1: with revision ID  e.g. gcp-hello-00001-779-uc.a.run.app
_CR_WITH_REVISION = re.compile(r"^(.+)-\d{5}-[a-z0-9]{3}-[a-z]{2,4}\.a\.run\.app$")
# Pattern 2: with random hash suffix  e.g. gcp-hello-boqrqyvx4a-uc.a.run.app
_CR_RANDOM_SUFFIX = re.compile(r"^([\w-]+?)-[a-z0-9]{6,}-[a-z]{2,4}\.a\.run\.app$")
# Pattern 3: base service URL  e.g. gcp-hello.uc.a.run.app
_CR_BASE_URL = re.compile(r"^([a-z0-9-]+)\.[a-z]{2,4}\.a\.run\.app$")


def _dedup_key(service: str, title: str) -> tuple[str, str]:
    return (service.lower(), str(hash(title.lower()[:60])))


def _check_and_register(service: str, title: str, severity: str) -> bool:
    """Return True if this is a duplicate (within TTL). Register if not."""
    _short_sevs = {s.strip() for s in settings.pagemenot_dedup_short_ttl_severities.split(",")}
    ttl = (
        settings.pagemenot_dedup_ttl_short
        if severity in _short_sevs
        else settings.pagemenot_dedup_ttl_long
    )
    key = _dedup_key(service, title)
    now = time.monotonic()
    with _dedup_lock:
        expired = [k for k, exp in _active_incidents.items() if now > exp]
        for k in expired:
            del _active_incidents[k]
        if key in _active_incidents:
            return True
        _active_incidents[key] = now + ttl
        _save_dedup()
        return False


def _clear_dedup(service: str, title: str) -> None:
    key = _dedup_key(service, title)
    with _dedup_lock:
        _active_incidents.pop(key, None)
        _save_dedup()


# Import scenarios for mock seeding
SCENARIOS = None
_scenarios_lock = threading.Lock()


def _load_scenarios():
    """Lazy-load scenarios from simulator."""
    global SCENARIOS
    with _scenarios_lock:
        if SCENARIOS is not None:
            return
        try:
            import importlib.util
            from pathlib import Path

            spec_path = Path(__file__).parent.parent / "scripts" / "simulate_incident.py"
            if spec_path.exists():
                spec = importlib.util.spec_from_file_location("simulator", spec_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    SCENARIOS = mod.SCENARIOS
                else:
                    SCENARIOS = {}
            else:
                SCENARIOS = {}
        except Exception:
            SCENARIOS = {}


@dataclass
class TriageResult:
    alert_title: str
    service: str
    severity: str
    monitor_report: str = ""
    root_cause: str = ""
    confidence: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    similar_incidents: list[str] = field(default_factory=list)
    remediation_steps: list[str] = field(default_factory=list)
    needs_approval: list[str] = field(default_factory=list)
    pending_exec_steps: list[str] = field(
        default_factory=list
    )  # runbook <!-- exec: --> steps awaiting approval
    postmortem_draft: str = ""
    raw_output: str = ""
    duration_seconds: float = 0.0
    suppressed: bool = False  # True = dedup or severity gate, crew never ran
    resolved_automatically: bool = False  # True = runbook exec succeeded
    execution_log: list[str] = field(default_factory=list)
    alarm_name: str = (
        ""  # CW alarm name — set for SNS-sourced incidents, enables post-exec verification
    )
    region: str = ""  # AWS region for CW polling
    cloud_provider: list[str] = field(
        default_factory=lambda: ["generic"]
    )  # list of providers: "aws", "gcp", "k8s", "hetzner", "onprem", "azure", "generic"
    _op: str = ""  # Azure alertContext operationName — enriches runbook RAG query


_CP_NORM: dict[str, str] = {
    # AWS
    "aws": "aws",
    "amazon": "aws",
    "ec2": "aws",
    "ecs": "aws",
    "rds": "aws",
    "lambda": "aws",
    "s3": "aws",
    "cloudwatch": "aws",
    # GCP
    "gcp": "gcp",
    "google": "gcp",
    "gce": "gcp",
    "googlecloud": "gcp",
    "google-cloud": "gcp",
    "cloud-run": "gcp",
    "cloud-sql": "gcp",
    # Azure
    "azure": "azure",
    "az": "azure",
    "aks": "azure",
    "blob": "azure",
    "cosmosdb": "azure",
    "app-service": "azure",
    "azure-vm": "azure",
    # K8s
    "k8s": "k8s",
    "kubernetes": "k8s",
    "kubectl": "k8s",
    "gke": "k8s",
    "eks": "k8s",
    # Hetzner (Linux VMs — shell commands, no cloud CLI)
    "hetzner": "hetzner",
    "hetzner-cloud": "hetzner",
    "htz": "hetzner",
    # On-prem / bare-metal
    "onprem": "onprem",
    "on-prem": "onprem",
    "on_prem": "onprem",
    "bare-metal": "onprem",
    "baremetal": "onprem",
    "metal": "onprem",
}


def _normalize_cloud_provider(raw: str) -> list[str]:
    """Map a raw provider string to a list of normalized provider names."""
    key = raw.strip().lower()
    if not key:
        default = settings.pagemenot_default_cloud_provider
        return [default] if default else ["generic"]
    normalized = _CP_NORM.get(key) or settings.pagemenot_cloud_provider_aliases.get(key)
    return [normalized] if normalized else ["generic"]


_GCP_TEXT_KW = ("gcp", "gce", "cloud run", "cloud sql", "cloudsql", "bigquery", "spanner")
_AWS_TEXT_KW = ("aws", "amazon", "ec2 ", "rds ", "cloudwatch", "ecs ", "lambda", " s3 ")


def _detect_cp_from_text(title: str, description: str) -> list[str]:
    text = (title + " " + description).lower()
    if any(k in text for k in _GCP_TEXT_KW):
        return ["gcp"]
    if any(k in text for k in _AWS_TEXT_KW):
        return ["aws"]
    return _normalize_cloud_provider("")


def _parse_alert(source: str, payload: dict) -> dict:
    """Normalize any alert source into standard fields."""
    _default_cp = _normalize_cloud_provider("")
    if source == "pagerduty":
        _pd_title = payload.get("title", payload.get("description", "Unknown"))
        _pd_desc = payload.get("description", "")
        return {
            "title": _pd_title,
            "service": payload.get("service", {}).get("name", "unknown"),
            "severity": "critical" if payload.get("urgency") == "high" else "medium",
            "description": _pd_desc,
            "external_id": payload.get("id", ""),
            "cloud_provider": _detect_cp_from_text(_pd_title, _pd_desc),
        }
    elif source == "opsgenie":
        priority_map = {"P1": "critical", "P2": "high", "P3": "medium", "P4": "low", "P5": "low"}
        _og_title = payload.get("message", "Unknown")
        _og_desc = payload.get("description", "")
        return {
            "title": _og_title,
            "service": payload.get("entity", payload.get("alias", "unknown")),
            "severity": priority_map.get(payload.get("priority", "P3"), "medium"),
            "description": _og_desc,
            "external_id": payload.get("alertId", ""),
            "cloud_provider": _detect_cp_from_text(_og_title, _og_desc),
        }
    elif source == "datadog":
        tags_raw = payload.get("tags", [])
        if isinstance(tags_raw, list):
            tags = {k: v for k, v in (t.split(":", 1) for t in tags_raw if ":" in t)}
        else:
            tags = tags_raw if isinstance(tags_raw, dict) else {}
        _dd_cp = _normalize_cloud_provider(tags.get("cloud_provider", tags.get("cloud", "")))
        return {
            "title": payload.get("title", payload.get("event_title", "Unknown")),
            "service": tags.get("service", _guess_service(str(payload))),
            "severity": "critical" if payload.get("alert_type") == "error" else "medium",
            "description": payload.get("body", payload.get("text", "")),
            "external_id": str(payload.get("id", "")),
            "cloud_provider": _dd_cp,
        }
    elif source == "newrelic":
        _nr_targets = payload.get("targets", [])
        _nr_labels = _nr_targets[0].get("labels", {}) if _nr_targets else {}
        _nr_provider = _nr_labels.get("provider", _nr_labels.get("cloud", "")).upper()
        _NR_CP = {"GCP": "gcp", "GOOGLE": "gcp", "AWS": "aws", "AMAZON": "aws", "AZURE": "azure"}
        _nr_cloud = [_NR_CP[_nr_provider]] if _nr_provider in _NR_CP else _default_cp
        return {
            "title": payload.get("name", payload.get("condition_name", "Unknown")),
            "service": _nr_targets[0].get("name", "unknown") if _nr_targets else "unknown",
            "severity": "critical"
            if payload.get("severity", "").upper() == "CRITICAL"
            else "medium",
            "description": payload.get("details", ""),
            "external_id": str(payload.get("incident_id", "")),
            "cloud_provider": _nr_cloud,
        }
    elif source == "grafana":
        alerts = payload.get("alerts", [{}])
        first = alerts[0] if alerts else {}
        labels = first.get("labels", {})
        _gf_raw = labels.get("cloud_provider", labels.get("cloud", labels.get("provider", "")))
        _gf_provider = _normalize_cloud_provider(_gf_raw)
        if _gf_provider == ["generic"]:
            _gf_text = (labels.get("alertname", "") + " " + payload.get("title", "")).lower()
            if any(k in _gf_text for k in ("gcp", "gce", "cloud run", "cloud sql")):
                _gf_provider = ["gcp"]
            elif any(k in _gf_text for k in ("aws", "amazon")):
                _gf_provider = ["aws"]
        return {
            "title": payload.get("title", labels.get("alertname", "Unknown")),
            "service": labels.get("service", labels.get("job", "unknown")),
            "severity": labels.get("severity", "medium"),
            "description": payload.get("message", ""),
            "cloud_provider": _gf_provider,
        }
    elif source == "alertmanager":
        labels = payload.get("labels", {})
        annotations = payload.get("annotations", {})
        _am_cp = _normalize_cloud_provider(labels.get("cloud_provider", labels.get("cloud", "")))
        return {
            "title": labels.get("alertname", "Unknown"),
            "service": labels.get("service", labels.get("job", "unknown")),
            "severity": labels.get("severity", "medium"),
            "description": annotations.get("description", annotations.get("summary", "")),
            "cloud_provider": _am_cp,
        }
    elif source == "sns":
        return {
            "title": payload.get("title", payload.get("alarm_name", "")),
            "service": payload.get("service", "unknown"),
            "severity": payload.get("severity", "high"),
            "description": payload.get("message", ""),
            "external_id": payload.get("alarm_name", ""),
            "alarm_name": payload.get("alarm_name", ""),
            "region": payload.get("region", ""),
            "cloud_provider": ["aws"],
        }
    elif source == "azure":
        _az_sev = {
            "Sev0": "critical",
            "Sev1": "high",
            "Sev2": "medium",
            "Sev3": "low",
            "Sev4": "low",
        }
        essentials = payload.get("data", {}).get("essentials", {})
        if not essentials:
            text = str(payload)
            return {
                "title": payload.get("alertRule", payload.get("name", text[:80])),
                "service": _guess_service(text),
                "severity": "medium",
                "description": text[:200],
                "external_id": "",
                "cloud_provider": ["azure"],
            }
        target_ids = essentials.get("alertTargetIDs", [])
        raw_target = target_ids[0] if target_ids else ""
        service = (
            raw_target.rstrip("/").split("/")[-1]
            if raw_target
            else (essentials.get("configurationItems", ["unknown"])[0])
        )
        alert_ctx = payload.get("data", {}).get("alertContext", {})
        _op = (
            alert_ctx.get("operationName")
            or (alert_ctx.get("properties") or {}).get("operationName")
            or ""
        ).lower()
        _sev = _az_sev.get(essentials.get("severity", "Sev2"), "medium")
        if any(x in _op for x in ("deallocate", "stop", "delete")):
            _sev = "critical"
        return {
            "title": essentials.get("alertRule", "Unknown Azure Alert"),
            "service": service,
            "severity": _sev,
            "description": essentials.get("description", ""),
            "external_id": essentials.get("alertId", ""),
            "cloud_provider": ["azure"],
        }
    elif source == "generic":
        incident = payload.get("incident", {})
        if incident:
            resource = incident.get("resource", {})
            resource_type = resource.get("type", "")
            labels = resource.get("labels", {})
            if resource_type == "cloud_run_revision":
                service = labels.get("service_name", "unknown")
            elif resource_type in ("gce_instance", "gke_container", "k8s_container"):
                service = incident.get("resource_display_name") or labels.get(
                    "instance_name", "unknown"
                )
            elif resource_type == "uptime_url":
                host = labels.get("host", "")
                m = (
                    _CR_WITH_REVISION.match(host)
                    or _CR_RANDOM_SUFFIX.match(host)
                    or _CR_BASE_URL.match(host)
                )
                service = (
                    m.group(1)
                    if m
                    else (
                        _guess_service(
                            incident.get("policy_name", "")
                            + " "
                            + incident.get("condition_name", "")
                        )
                        or "unknown"
                    )
                )
            else:
                display = incident.get("resource_display_name", "")
                service = (
                    (display if ("-" in display or "_" in display) else None)
                    or labels.get("service_name")
                    or _guess_service(incident.get("condition_name", ""))
                    or "unknown"
                )
            state = incident.get("state", "open")
            severity = "high" if state == "open" else "low"
            return {
                "title": incident.get("condition_name", "Unknown GCP Alert"),
                "service": service,
                "severity": severity,
                "description": incident.get("summary", incident.get("url", "")),
                "cloud_provider": ["gcp"],
            }
        text = payload.get("text", payload.get("description", str(payload)))
        return {
            "title": text[:100],
            "service": _guess_service(text),
            "severity": "medium",
            "description": text,
            "cloud_provider": _default_cp,
        }
    else:
        text = payload.get("text", payload.get("description", str(payload)))
        return {
            "title": text[:100],
            "service": _guess_service(text),
            "severity": "medium",
            "description": text,
            "cloud_provider": _default_cp,
        }


_REDACT_CREDENTIAL_RE = re.compile(
    r"((?:password|passwd|secret|token|api.?key|authorization|bearer|aws.?secret"
    r"|private.?key|username|user|login|db.?user|database.?user)"
    r'\s*[:=]\s*)[^\s,\'";&\n]{2,}',
    re.IGNORECASE,
)
_REDACT_DSN_RE = re.compile(
    r'(?:postgresql|postgres|mysql|mongodb|redis|amqp|amqps|jdbc:\w+)://[^\s\'"<>\n]+',
    re.IGNORECASE,
)
_REDACT_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _redact_sensitive(text: str) -> str:
    """Redact credentials, DSNs, and IP addresses before sending context to an LLM."""
    text = _REDACT_CREDENTIAL_RE.sub(r"\1[REDACTED]", text)
    text = _REDACT_DSN_RE.sub("[DSN_REDACTED]", text)
    text = _REDACT_IPV4_RE.sub("[IP_REDACTED]", text)
    return text


def _guess_service(text: str) -> str:
    for word in text.split():
        clean = word.strip(".,!?:;'\"")
        if "-" in clean or "_" in clean:
            return clean
    return "unknown"


def _seed_mock_if_needed(parsed_alert: dict):
    """If mock tools are in use, seed them with scenario data matching this alert."""
    from pagemenot.mock_tools import seed_mock_context

    _load_scenarios()
    service = parsed_alert["service"]

    # Find a matching scenario by service name
    for scenario_name, scenario in (SCENARIOS or {}).items():
        pd = scenario.get("pagerduty", {})
        if pd.get("service", {}).get("name") == service:
            seed_mock_context(
                {
                    "service": service,
                    "pagerduty": pd,
                    "mock_metrics": scenario.get("mock_metrics", {}),
                    "mock_logs": scenario.get("mock_logs", []),
                    "mock_deploys": scenario.get("mock_deploys", []),
                    "mock_k8s": scenario.get("mock_k8s", {}),
                }
            )
            logger.info(f"Mock context seeded: {scenario_name}")
            return

    logger.debug(f"No mock scenario found for service '{service}', using defaults")


def _run_crew_sync(alert_summary: str, cloud_provider: str = "generic") -> str:
    """Run the crew synchronously (in thread pool)."""
    from pagemenot.crew import build_triage_crew

    crew = build_triage_crew(alert_summary, cloud_provider=cloud_provider)
    result = crew.kickoff()
    return str(result)


def _parse_crew_output(raw: str, parsed_alert: dict) -> TriageResult:
    """Extract structured fields from crew output text."""
    result = TriageResult(
        alert_title=parsed_alert["title"],
        service=parsed_alert["service"],
        severity=parsed_alert["severity"],
        raw_output=raw,
        _op=parsed_alert.get("_op", ""),
    )

    lower = raw.lower()

    # Root cause
    for marker in ["root cause:", "root cause analysis:", "**root cause"]:
        if marker in lower:
            idx = lower.index(marker)
            chunk = raw[idx : idx + 500]
            lines = chunk.split("\n")
            result.root_cause = (
                lines[1].strip(" -•*") if len(lines) > 1 else lines[0].split(":", 1)[-1].strip()
            )[:300]
            break

    # Confidence — match any "confidence" label adjacent to high/medium/low
    for level in ["high", "medium", "low"]:
        if (
            f"confidence: {level}" in lower
            or f"confidence level: {level}" in lower
            or f"confidence*: {level}" in lower
            or f"| {level}" in lower
            or re.search(rf"\bconfidence\b[^:\n]{{0,10}}:?\s*\*?{level}\b", lower)
        ):
            result.confidence = level
            break

    # Remediation steps (AUTO-SAFE and NEEDS APPROVAL)
    for line in raw.split("\n"):
        stripped = line.strip(" -•*[]")
        if "[AUTO-SAFE]" in line:
            result.remediation_steps.append(stripped)
        if "NEEDS APPROVAL" in line or "HUMAN APPROVAL" in line:
            result.needs_approval.append(stripped)

    if not result.root_cause:
        result.root_cause = "See detailed analysis below."

    return result


async def _try_runbook_exec(result: TriageResult):
    """Attempt autonomous runbook execution. Mutates result in place.

    <!-- exec: cmd -->         → always runs immediately (DRY_RUN aware)
    <!-- exec:approve: cmd --> → always queued in result.pending_exec_steps for human approval
    """
    if not settings.pagemenot_exec_enabled:
        return

    from pagemenot.tools import get_runbook_exec_steps, dispatch_exec_step

    # Only use tagged steps from verified runbook files.
    # LLM-generated text is NEVER passed to dispatch_exec_step — prompt injection risk.
    # Query with alert title + root cause + operationName for better runbook disambiguation
    query = result.alert_title
    if result.root_cause and result.root_cause != "See detailed analysis below.":
        query = f"{result.alert_title}. {result.root_cause}"
    _op = getattr(result, "_op", "") or ""
    if _op:
        query = f"{query}. operation: {_op}"
    step_map = get_runbook_exec_steps(
        query, service=result.service, cloud_providers=result.cloud_provider
    )
    auto_steps: list[tuple[str, str]] = step_map["auto"]
    approve_steps: list[tuple[str, str]] = step_map["approve"]

    if not auto_steps and not approve_steps:
        return

    # Queue approve steps — always requires human sign-off (tag-driven, not config-driven)
    if approve_steps:
        result.pending_exec_steps = [tag for tag, _ in approve_steps]
        approve_runbooks = sorted({fn for _, fn in approve_steps})
        logger.info(
            f"[APPROVAL QUEUED] {len(approve_steps)} step(s) queued for approval from: {approve_runbooks}"
        )

    # Run auto steps only — approve steps always wait for human
    pairs_to_run = auto_steps
    if not pairs_to_run:
        return

    mode = "DRY RUN" if settings.pagemenot_exec_dry_run else "EXEC"
    runbooks_used = sorted({fn for _, fn in pairs_to_run})
    logger.info(f"[{mode}] {len(pairs_to_run)} step(s) from {runbooks_used} for {result.service}")
    from pagemenot.tools import ExecSkipped

    loop = asyncio.get_running_loop()
    all_ok = True
    steps_executed = 0
    for tag, filename in pairs_to_run:
        try:
            output = await loop.run_in_executor(_executor, dispatch_exec_step, tag, result.service)
            display_tag = tag.replace("{{ service }}", result.service or "UNKNOWN_SERVICE").replace(
                "{{ resource_group }}", settings.azure_resource_group or "pagemenot-rg"
            )
            result.execution_log.append(
                f"📖 *{filename}*\n✅ `{display_tag[:120]}`\n```{output[:300]}```"
            )
            logger.info(f"Exec step succeeded [{filename}]: {tag[:80]}")
            steps_executed += 1
        except ExecSkipped as e:
            display_tag = tag.replace("{{ service }}", result.service or "UNKNOWN_SERVICE").replace(
                "{{ resource_group }}", settings.azure_resource_group or "pagemenot-rg"
            )
            result.execution_log.append(f"📖 *{filename}*\n⏭️ `{display_tag[:120]}`\n```{e}```")
            logger.info(f"Exec step skipped [{filename}]: {tag[:80]} — {e}")
        except Exception as e:
            display_tag = tag.replace("{{ service }}", result.service or "UNKNOWN_SERVICE").replace(
                "{{ resource_group }}", settings.azure_resource_group or "pagemenot-rg"
            )
            result.execution_log.append(f"📖 *{filename}*\n❌ `{display_tag[:120]}`\n```{e}```")
            logger.warning(f"Exec step failed [{filename}]: {tag[:80]} — {e}")
            all_ok = False
            break

    if all_ok and steps_executed > 0 and not result.pending_exec_steps:
        result.resolved_automatically = True
        logger.info(f"Incident auto-resolved: {result.alert_title}")


async def run_triage(source: str, payload: dict[str, Any]) -> TriageResult:
    """The ONE entry point for all triage. Handles mock + real transparently."""
    start = datetime.now(timezone.utc)

    # 1. Parse
    parsed = _parse_alert(source, payload)
    logger.info(f"Triaging: {parsed['title']} (service={parsed['service']})")

    # 2. Dedup check
    if _check_and_register(parsed["service"], parsed["title"], parsed["severity"]):
        logger.info(f"Duplicate suppressed: {parsed['title']}")
        return TriageResult(
            alert_title=parsed["title"],
            service=parsed["service"],
            severity=parsed["severity"],
            suppressed=True,
            duration_seconds=0.0,
        )

    # 3. Seed mocks if real integrations aren't configured
    _seed_mock_if_needed(parsed)

    # 5. Build summary for the crew — redact credentials before sending to LLM
    raw_description = parsed.get("description", "N/A")
    summary = _redact_sensitive(
        f"**Alert:** {parsed['title']}\n"
        f"**Service:** {parsed['service']}\n"
        f"**Cloud Provider:** {', '.join(parsed['cloud_provider'])}\n"
        f"**Severity:** {parsed['severity']}\n"
        f"**Description:** {raw_description}\n"
        f"**Time:** {datetime.now(timezone.utc).isoformat()}"
    )

    # 6. Run crew
    from pagemenot.tools import _triage_cloud_provider

    _triage_cloud_provider.set(parsed.get("cloud_provider", []))
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        _executor, _run_crew_sync, summary, ",".join(parsed.get("cloud_provider", ["generic"]))
    )

    # 7. Parse output
    result = _parse_crew_output(raw, parsed)

    result.alarm_name = parsed.get("alarm_name", "")
    result.region = parsed.get("region", "")
    result.cloud_provider = parsed.get("cloud_provider", ["generic"])

    # 8. Attempt runbook-driven resolution (only if exec is enabled)
    await _try_runbook_exec(result)

    result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        f"Triage done in {result.duration_seconds:.1f}s (resolved={result.resolved_automatically})"
    )
    return result
