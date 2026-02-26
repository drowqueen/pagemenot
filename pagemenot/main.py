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
from pagemenot.slack_bot import create_slack_app
from pagemenot.triage import run_triage

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
        if msg.get("event") == "incident.trigger":
            asyncio.create_task(_auto_triage("pagerduty", msg.get("incident", {})))
    return {"status": "accepted"}


@app.post("/webhooks/grafana")
async def grafana_webhook(request: Request):
    payload = await request.json()
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
    asyncio.create_task(_auto_triage("newrelic", payload))
    return {"status": "accepted"}


async def _auto_triage(source: str, payload: dict):
    """Run triage and post to the configured Slack channel."""
    try:
        from pagemenot.slack_bot import get_client

        result = await run_triage(source=source, payload=payload)
        client = get_client()

        sev = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(result.severity, "⚪")

        # Post headline
        resp = await client.chat_postMessage(
            channel=settings.pagemenot_channel,
            text=f"{sev} *INCIDENT: {result.alert_title}*",
        )
        thread = resp["ts"]

        # Post root cause in thread
        conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")
        await client.chat_postMessage(
            channel=settings.pagemenot_channel,
            thread_ts=thread,
            text=(
                f"*🔍 Root Cause* (confidence: {conf} {result.confidence})\n\n"
                f"{result.root_cause}\n\n"
                f"⏱️ Triaged in {result.duration_seconds:.1f}s"
            ),
        )

        # Post full analysis
        if result.raw_output:
            truncated = result.raw_output[:2900]
            await client.chat_postMessage(
                channel=settings.pagemenot_channel,
                thread_ts=thread,
                text=f"```{truncated}```",
            )

    except Exception as e:
        logger.error(f"Auto-triage failed: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pagemenot.main:app", host="0.0.0.0", port=8080, log_level="info")
