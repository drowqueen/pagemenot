"""
Pagemenot — AI SRE Crew.

Entry point. Starts FastAPI (webhooks) + Slack bot (Socket Mode).
Teams run: docker compose up -d
That's it. Everything auto-configures.
"""

import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from pagemenot.config import settings
from pagemenot.knowledge.rag import ingest_all
from pagemenot.slack_bot import create_slack_app, _chunk_text
from pagemenot.triage import run_triage, _executor

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pagemenot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Slack bot on startup, clean up on shutdown."""

    # Ingest knowledge base (postmortems + runbooks → ChromaDB)
    ingest_all()

    # Boot Slack
    slack_app = create_slack_app()
    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    task = asyncio.create_task(handler.start_async())

    # Store for webhook handlers
    app.state.slack_app = slack_app

    logger.info("═" * 50)
    logger.info("🦞 Pagemenot is online")
    logger.info(f"   LLM: {settings.llm_provider}/{settings.llm_model}")
    logger.info(f"   Integrations: {settings.enabled_integrations or ['none — add via .env']}")
    logger.info(f"   Slack channel: #{settings.pagemenot_channel}")
    logger.info("═" * 50)

    yield

    task.cancel()
    _executor.shutdown(wait=False)


app = FastAPI(title="Pagemenot", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "integrations": settings.enabled_integrations,
    }


# ── Webhook receivers ─────────────────────────────────────
# Teams point their PagerDuty/Grafana/Alertmanager webhooks
# here. Pagemenot auto-detects the format and triages.

@app.post("/webhooks/pagerduty")
async def pagerduty_webhook(request: Request):
    payload = await request.json()
    for msg in payload.get("messages", []):
        # PagerDuty v2 webhook event type is "incident.triggered"
        if msg.get("event") == "incident.triggered":
            asyncio.create_task(_auto_triage("pagerduty", msg.get("incident", {})))
    return {"status": "accepted"}


@app.post("/webhooks/grafana")
async def grafana_webhook(request: Request):
    payload = await request.json()
    # Only triage firing alerts — skip resolved/ok state webhooks
    if payload.get("status") == "firing":
        asyncio.create_task(_auto_triage("grafana", payload))
    return {"status": "accepted"}


@app.post("/webhooks/alertmanager")
async def alertmanager_webhook(request: Request):
    payload = await request.json()
    for alert in payload.get("alerts", []):
        if alert.get("status") == "firing":
            asyncio.create_task(_auto_triage("alertmanager", alert))
    return {"status": "accepted"}


@app.post("/webhooks/generic")
async def generic_webhook(request: Request):
    """Catch-all for any alert source. Just POST JSON with a 'title' or 'message'."""
    payload = await request.json()
    asyncio.create_task(_auto_triage("generic", payload))
    return {"status": "accepted"}


@app.post("/webhooks/opsgenie")
async def opsgenie_webhook(request: Request):
    payload = await request.json()
    # OpsGenie sends action + alert fields
    if payload.get("action") in ("Create", "Acknowledge") and payload.get("alert"):
        asyncio.create_task(_auto_triage("opsgenie", payload["alert"]))
    return {"status": "accepted"}


@app.post("/webhooks/datadog")
async def datadog_webhook(request: Request):
    payload = await request.json()
    if payload.get("alert_type") != "success":  # skip recoveries
        asyncio.create_task(_auto_triage("datadog", payload))
    return {"status": "accepted"}


@app.post("/webhooks/newrelic")
async def newrelic_webhook(request: Request):
    payload = await request.json()
    # Only triage open incidents — skip acknowledged/closed states
    if payload.get("state", "open") == "open":
        asyncio.create_task(_auto_triage("newrelic", payload))
    return {"status": "accepted"}


async def _auto_triage(source: str, payload: dict):
    """Run triage and route result based on severity and resolution status."""
    try:
        from pagemenot.slack_bot import get_client

        result = await run_triage(source=source, payload=payload)
        client = get_client()
        channel = settings.pagemenot_channel

        # Suppressed (duplicate or low-severity)
        if result.suppressed:
            sev_label = "Low-severity" if result.severity == "low" else "Duplicate"
            await client.chat_postMessage(
                channel=channel,
                text=f"⚪ {sev_label} suppressed: {result.alert_title} ({result.service})",
            )
            return

        # Auto-resolved by runbook execution
        if result.resolved_automatically:
            log_text = "\n".join(result.execution_log) if result.execution_log else "No steps logged."
            dry = settings.pagemenot_exec_dry_run
            await client.chat_postMessage(
                channel=channel,
                text=(
                    f"{'🔵 *Dry run* —' if dry else '✅'} *{'Would have resolved' if dry else 'Auto-resolved'}:* {result.alert_title}\n"
                    f"Service: {result.service} | ⏱️ {result.duration_seconds:.1f}s\n\n"
                    f"*{'Steps that would execute' if dry else 'Steps executed'}:*\n{log_text}"
                ),
            )
            return

        sev = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(result.severity, "⚪")
        conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")

        # Medium: quiet post — no INCIDENT caps, no on-call ping
        if result.severity == "medium":
            resp = await client.chat_postMessage(
                channel=channel,
                text=f"{sev} {result.alert_title} — triage complete",
            )
            thread = resp["ts"]
        else:
            # Critical / high: loud headline
            resp = await client.chat_postMessage(
                channel=channel,
                text=f"{sev} *INCIDENT: {result.alert_title}*",
            )
            thread = resp["ts"]

        # Post root cause + analysis in thread
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread,
            text=(
                f"*🔍 Root Cause* (confidence: {conf} {result.confidence})\n\n"
                f"{result.root_cause}\n\n"
                f"⏱️ Triaged in {result.duration_seconds:.1f}s"
            ),
        )

        if result.raw_output:
            for i, chunk in enumerate(_chunk_text(result.raw_output, 2900)[:3]):
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"Detailed analysis (part {i + 1})\n```{chunk}```",
                )

        # Escalate critical/high to on-call channel
        if result.severity in ("critical", "high") and settings.pagemenot_oncall_channel:
            await client.chat_postMessage(
                channel=settings.pagemenot_oncall_channel,
                text=(
                    f"{sev} *ESCALATION:* {result.alert_title} ({result.service})\n"
                    f"Confidence: {conf} {result.confidence} — see #{channel}"
                ),
            )

    except Exception as e:
        logger.error(f"Auto-triage failed: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pagemenot.main:app", host="0.0.0.0", port=8080, log_level="info")
