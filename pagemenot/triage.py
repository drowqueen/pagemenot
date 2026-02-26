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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from pagemenot.config import settings

logger = logging.getLogger("pagemenot.triage")
_executor = ThreadPoolExecutor(max_workers=3)

# Import scenarios for mock seeding
SCENARIOS = None


def _load_scenarios():
    """Lazy-load scenarios from simulator."""
    global SCENARIOS
    if SCENARIOS is None:
        try:
            # Import from the simulate_incident script
            import importlib.util
            import sys
            from pathlib import Path

            spec_path = Path(__file__).parent.parent / "scripts" / "simulate_incident.py"
            if spec_path.exists():
                spec = importlib.util.spec_from_file_location("simulator", spec_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                SCENARIOS = mod.SCENARIOS
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
    raw_output: str = ""
    duration_seconds: float = 0.0


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


def _run_crew_sync(alert_summary: str) -> str:
    """Run the crew synchronously (in thread pool)."""
    from pagemenot.crew import build_crew, build_triage_tasks

    crew = build_crew()
    agents = crew.agents

    tasks = build_triage_tasks(
        alert_summary=alert_summary,
        monitor_agent=agents[0],
        diagnoser_agent=agents[1],
        remediator_agent=agents[2],
    )

    crew.tasks = tasks
    result = crew.kickoff()
    return str(result)


def _parse_crew_output(raw: str, parsed_alert: dict) -> TriageResult:
    """Extract structured fields from crew output text."""
    result = TriageResult(
        alert_title=parsed_alert["title"],
        service=parsed_alert["service"],
        severity=parsed_alert["severity"],
        raw_output=raw,
    )

    lower = raw.lower()

    # Root cause
    for marker in ["root cause:", "root cause analysis:", "**root cause"]:
        if marker in lower:
            idx = lower.index(marker)
            chunk = raw[idx:idx + 500]
            lines = chunk.split("\n")
            result.root_cause = (lines[1].strip(" -•*") if len(lines) > 1
                                 else lines[0].split(":", 1)[-1].strip())[:300]
            break

    # Confidence
    for level in ["high", "medium", "low"]:
        if f"confidence: {level}" in lower or f"confidence level: {level}" in lower:
            result.confidence = level
            break

    # Approval-gated actions
    for line in raw.split("\n"):
        if "NEEDS APPROVAL" in line or "HUMAN APPROVAL" in line:
            result.needs_approval.append(line.strip(" -•*[]"))

    if not result.root_cause:
        result.root_cause = "See detailed analysis below."

    return result


async def run_triage(source: str, payload: dict[str, Any]) -> TriageResult:
    """The ONE entry point for all triage. Handles mock + real transparently."""
    start = datetime.now(timezone.utc)

    # 1. Parse
    parsed = _parse_alert(source, payload)
    logger.info(f"Triaging: {parsed['title']} (service={parsed['service']})")

    # 2. Seed mocks if real integrations aren't configured
    _seed_mock_if_needed(parsed)

    # 3. Build summary for the crew
    summary = (
        f"**Alert:** {parsed['title']}\n"
        f"**Service:** {parsed['service']}\n"
        f"**Severity:** {parsed['severity']}\n"
        f"**Description:** {parsed.get('description', 'N/A')}\n"
        f"**Time:** {datetime.now(timezone.utc).isoformat()}"
    )

    # 4. Run crew
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(_executor, _run_crew_sync, summary)

    # 5. Parse + return
    result = _parse_crew_output(raw, parsed)
    result.duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()

    logger.info(f"Triage done in {result.duration_seconds:.1f}s")
    return result
