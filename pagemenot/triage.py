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
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.triage")
_executor = ThreadPoolExecutor(max_workers=3)

# ── Deduplication store ────────────────────────────────────────
# (service, title_hash) → expiry timestamp (time.monotonic())
_active_incidents: dict[tuple[str, str], float] = {}
_dedup_lock = threading.Lock()


def _dedup_key(service: str, title: str) -> tuple[str, str]:
    return (service.lower(), str(hash(title.lower()[:60])))


def _check_and_register(service: str, title: str, severity: str) -> bool:
    """Return True if this is a duplicate (within TTL). Register if not."""
    ttl = settings.pagemenot_dedup_ttl_short if severity in ("critical", "high") else settings.pagemenot_dedup_ttl_long
    key = _dedup_key(service, title)
    now = time.monotonic()
    with _dedup_lock:
        # Prune expired entries
        expired = [k for k, exp in _active_incidents.items() if now > exp]
        for k in expired:
            del _active_incidents[k]
        if key in _active_incidents:
            return True
        _active_incidents[key] = now + ttl
        return False

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
    postmortem_draft: str = ""
    postmortem_path: str = ""
    pending_review: bool = False
    raw_output: str = ""
    duration_seconds: float = 0.0
    suppressed: bool = False              # True = dedup or severity gate, crew never ran
    resolved_automatically: bool = False  # True = runbook exec succeeded
    execution_log: list[str] = field(default_factory=list)


def _parse_alert(source: str, payload: dict) -> dict:
    """Normalize any alert source into standard fields."""
    if source == "pagerduty":
        return {
            "title": payload.get("title", payload.get("description", "Unknown")),
            "service": payload.get("service", {}).get("name", "unknown"),
            "severity": "critical" if payload.get("urgency") == "high" else "medium",
            "description": payload.get("description", ""),
            "external_id": payload.get("id", ""),
        }
    elif source == "opsgenie":
        priority_map = {"P1": "critical", "P2": "high", "P3": "medium", "P4": "low", "P5": "low"}
        return {
            "title": payload.get("message", "Unknown"),
            "service": payload.get("entity", payload.get("alias", "unknown")),
            "severity": priority_map.get(payload.get("priority", "P3"), "medium"),
            "description": payload.get("description", ""),
            "external_id": payload.get("alertId", ""),
        }
    elif source == "datadog":
        # Datadog sends tags as a list of "key:value" strings, not a dict
        tags_raw = payload.get("tags", [])
        if isinstance(tags_raw, list):
            tags = {k: v for k, v in (t.split(":", 1) for t in tags_raw if ":" in t)}
        else:
            tags = tags_raw if isinstance(tags_raw, dict) else {}
        return {
            "title": payload.get("title", payload.get("event_title", "Unknown")),
            "service": tags.get("service", _guess_service(str(payload))),
            "severity": "critical" if payload.get("alert_type") == "error" else "medium",
            "description": payload.get("body", payload.get("text", "")),
            "external_id": str(payload.get("id", "")),
        }
    elif source == "newrelic":
        return {
            "title": payload.get("name", payload.get("condition_name", "Unknown")),
            "service": payload.get("targets", [{}])[0].get("name", "unknown") if payload.get("targets") else "unknown",
            "severity": "critical" if payload.get("severity", "").upper() == "CRITICAL" else "medium",
            "description": payload.get("details", ""),
            "external_id": str(payload.get("incident_id", "")),
        }
    elif source == "grafana":
        alerts = payload.get("alerts", [{}])
        first = alerts[0] if alerts else {}
        labels = first.get("labels", {})
        return {
            "title": payload.get("title", labels.get("alertname", "Unknown")),
            "service": labels.get("service", labels.get("job", "unknown")),
            "severity": labels.get("severity", "medium"),
            "description": payload.get("message", ""),
        }
    elif source == "alertmanager":
        labels = payload.get("labels", {})
        annotations = payload.get("annotations", {})
        return {
            "title": labels.get("alertname", "Unknown"),
            "service": labels.get("service", labels.get("job", "unknown")),
            "severity": labels.get("severity", "medium"),
            "description": annotations.get("description", annotations.get("summary", "")),
        }
    else:
        text = payload.get("text", payload.get("description", str(payload)))
        return {
            "title": text[:100],
            "service": _guess_service(text),
            "severity": "medium",
            "description": text,
        }


_REDACT_CREDENTIAL_RE = re.compile(
    r'((?:password|passwd|secret|token|api.?key|authorization|bearer|aws.?secret'
    r'|private.?key|username|user|login|db.?user|database.?user)'
    r'\s*[:=]\s*)[^\s,\'";&\n]{2,}',
    re.IGNORECASE,
)
_REDACT_DSN_RE = re.compile(
    r'(?:postgresql|postgres|mysql|mongodb|redis|amqp|amqps|jdbc:\w+)://[^\s\'"<>\n]+',
    re.IGNORECASE,
)
_REDACT_IPV4_RE = re.compile(
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
)


def _redact_sensitive(text: str) -> str:
    """Redact credentials, DSNs, and IP addresses before sending context to an LLM."""
    text = _REDACT_CREDENTIAL_RE.sub(r'\1[REDACTED]', text)
    text = _REDACT_DSN_RE.sub('[DSN_REDACTED]', text)
    text = _REDACT_IPV4_RE.sub('[IP_REDACTED]', text)
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
            seed_mock_context({
                "service": service,
                "pagerduty": pd,
                "mock_metrics": scenario.get("mock_metrics", {}),
                "mock_logs": scenario.get("mock_logs", []),
                "mock_deploys": scenario.get("mock_deploys", []),
                "mock_k8s": scenario.get("mock_k8s", {}),
            })
            logger.info(f"Mock context seeded: {scenario_name}")
            return

    logger.debug(f"No mock scenario found for service '{service}', using defaults")


def _run_crew_sync(alert_summary: str) -> tuple[str, dict | None]:
    """Run the crew synchronously (in thread pool). Returns (raw_str, structured_dict | None)."""
    from pagemenot.crew import build_triage_crew

    crew = build_triage_crew(alert_summary)
    result = crew.kickoff()
    raw = str(result)
    structured = None
    if result.tasks_output:
        last = result.tasks_output[-1]
        if getattr(last, "json_dict", None):
            structured = last.json_dict
    return raw, structured


def _parse_crew_output(raw: str, structured: dict | None, parsed_alert: dict) -> TriageResult:
    """Build TriageResult from structured JSON output (preferred) or prose fallback."""
    result = TriageResult(
        alert_title=parsed_alert["title"],
        service=parsed_alert["service"],
        severity=parsed_alert["severity"],
        raw_output=raw,
    )

    if structured:
        result.root_cause = structured.get("root_cause", "")[:300]
        result.confidence = structured.get("confidence", "unknown")
        result.evidence = structured.get("evidence", [])
        steps = structured.get("remediation_steps", [])
        for step in steps:
            s = step if isinstance(step, str) else str(step)
            if "NEEDS APPROVAL" in s or "HUMAN APPROVAL" in s:
                result.needs_approval.append(s)
            else:
                result.remediation_steps.append(s)
        result.postmortem_draft = structured.get("postmortem_summary", "")
    else:
        # Prose fallback for LLMs that ignore output_json
        lower = raw.lower()
        for marker in ["root cause:", "root cause analysis:", "**root cause"]:
            if marker in lower:
                idx = lower.index(marker)
                chunk = raw[idx:idx + 500]
                lines = chunk.split("\n")
                result.root_cause = (lines[1].strip(" -•*") if len(lines) > 1
                                     else lines[0].split(":", 1)[-1].strip())[:300]
                break
        for level in ["high", "medium", "low"]:
            if f"confidence: {level}" in lower or f"confidence level: {level}" in lower:
                result.confidence = level
                break
        for line in raw.split("\n"):
            s = line.strip(" -•*[]")
            if "[AUTO-SAFE]" in line:
                result.remediation_steps.append(s)
            if "NEEDS APPROVAL" in line or "HUMAN APPROVAL" in line:
                result.needs_approval.append(s)

    if not result.root_cause:
        result.root_cause = "Root cause could not be determined — see raw analysis."

    return result


def _try_runbook_exec(result: TriageResult):
    """Attempt autonomous runbook execution. Mutates result in place."""
    if not settings.pagemenot_exec_enabled:
        return

    from pagemenot.tools import get_runbook_exec_steps, dispatch_exec_step

    # Only use <!-- exec: --> tagged steps from verified runbook files.
    # LLM-generated [AUTO-SAFE] text is NEVER used for autonomous execution
    # (prompt injection risk: attacker could craft alert text to inject commands).
    steps = get_runbook_exec_steps(result.alert_title, service=result.service)

    if not steps:
        return

    mode = "DRY RUN" if settings.pagemenot_exec_dry_run else "EXEC"
    logger.info(f"[{mode}] Attempting runbook exec: {len(steps)} step(s) for {result.service}")
    all_ok = True
    for step in steps:
        try:
            output = dispatch_exec_step(step, service=result.service)
            result.execution_log.append(f"✅ {step[:100]}: {output[:150]}")
            logger.info(f"Exec step succeeded: {step[:80]}")
        except Exception as e:
            result.execution_log.append(f"❌ {step[:100]}: {e}")
            logger.warning(f"Exec step failed: {step[:80]} — {e}")
            all_ok = False
            break  # stop on first failure, escalate with context

    if all_ok and steps:
        result.resolved_automatically = True
        logger.info(f"Incident auto-resolved: {result.alert_title}")


def _generate_postmortem_narrative(result: TriageResult) -> str:
    """Call the postmortem LLM to write a narrative RCA. Falls back to structured summary on error."""
    try:
        from pagemenot.crew import build_postmortem_llm
        llm = build_postmortem_llm()
        evidence_text = "\n".join(f"- {e}" for e in result.evidence) if result.evidence else "N/A"
        steps_text = "\n".join(f"- {s}" for s in result.remediation_steps) if result.remediation_steps else "N/A"
        prompt = (
            f"Write a concise incident postmortem narrative (3-4 paragraphs) for an SRE knowledge base.\n\n"
            f"Alert: {result.alert_title}\n"
            f"Service: {result.service}\n"
            f"Severity: {result.severity}\n"
            f"Root cause: {result.root_cause}\n"
            f"Evidence:\n{evidence_text}\n"
            f"Steps taken:\n{steps_text}\n"
            f"Auto-resolved: {result.resolved_automatically}\n\n"
            f"Write: (1) what happened and impact, (2) root cause analysis, "
            f"(3) resolution summary, (4) prevention recommendations. "
            f"Be specific and factual. No filler."
        )
        response = llm.call(messages=[{"role": "user", "content": prompt}])
        return response if isinstance(response, str) else str(response)
    except Exception as e:
        logger.warning(f"Postmortem narrative generation failed: {e}")
        return result.root_cause


def _write_postmortem(result: TriageResult) -> tuple[Path | None, bool]:
    """Write an auto-generated postmortem MD and index it if confidence is high."""
    from pagemenot.knowledge.rag import POSTMORTEMS_DIR, add_postmortem

    if result.confidence == "high":
        target_dir = POSTMORTEMS_DIR
        index = True
    elif result.confidence == "medium":
        target_dir = POSTMORTEMS_DIR.parent / "pending_review"
        index = False
    else:
        return None, False

    target_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^\w]+", "-", result.service.lower()).strip("-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filepath = target_dir / f"{slug}_{timestamp}.md"

    evidence_md = "\n".join(f"- {e}" for e in result.evidence) if result.evidence else "- N/A"
    remediation_md = "\n".join(f"- {s}" for s in result.remediation_steps) if result.remediation_steps else "- N/A"
    similar_md = "\n".join(f"- {s}" for s in result.similar_incidents) if result.similar_incidents else "- N/A"

    narrative = _generate_postmortem_narrative(result)

    content = (
        f"# Incident: {result.alert_title}\n\n"
        f"**Service:** {result.service}\n"
        f"**Severity:** {result.severity}\n"
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        f"**Resolved automatically:** {result.resolved_automatically}\n"
        f"**Triage confidence:** {result.confidence}\n\n"
        f"## Analysis\n\n{narrative}\n\n"
        f"## Root Cause\n\n{result.root_cause}\n\n"
        f"## Evidence\n\n{evidence_md}\n\n"
        f"## Remediation\n\n{remediation_md}\n\n"
        f"## Similar Incidents\n\n{similar_md}\n"
    )

    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Postmortem written: {filepath.name}")
        if index:
            add_postmortem(filepath)
        return filepath, not index
    except Exception as e:
        logger.warning(f"Postmortem write failed: {e}")
        return None, False


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

    # 3. Severity gate — skip crew for low-severity noise
    if parsed["severity"] == "low":
        logger.info(f"Low-severity suppressed: {parsed['title']}")
        return TriageResult(
            alert_title=parsed["title"],
            service=parsed["service"],
            severity="low",
            suppressed=True,
            duration_seconds=0.0,
        )

    # 4. Seed mocks if real integrations aren't configured
    _seed_mock_if_needed(parsed)

    # 5. Build summary for the crew — redact credentials before sending to LLM
    raw_description = parsed.get('description', 'N/A')
    summary = _redact_sensitive(
        f"**Alert:** {parsed['title']}\n"
        f"**Service:** {parsed['service']}\n"
        f"**Severity:** {parsed['severity']}\n"
        f"**Description:** {raw_description}\n"
        f"**Time:** {datetime.now(timezone.utc).isoformat()}"
    )

    # 6. Run crew
    loop = asyncio.get_running_loop()
    raw, structured = await loop.run_in_executor(_executor, _run_crew_sync, summary)

    # 7. Parse output
    result = _parse_crew_output(raw, structured, parsed)

    # 8. Write postmortem (high confidence → index; medium → pending_review)
    pm_path, pm_pending = _write_postmortem(result)
    if pm_path:
        result.postmortem_path = str(pm_path.name)
        result.pending_review = pm_pending

    # 9. Attempt runbook-driven resolution (only if exec is enabled)
    _try_runbook_exec(result)

    result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        f"Triage done in {result.duration_seconds:.1f}s "
        f"(resolved={result.resolved_automatically})"
    )
    return result
