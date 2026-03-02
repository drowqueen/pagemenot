"""
Pagemenot — AI SRE Crew.

Entry point. Starts FastAPI (webhooks) + Slack bot (Socket Mode).
Teams run: docker compose up -d
That's it. Everything auto-configures.
"""

import asyncio
import base64
import hashlib
import hmac
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from typing import Optional

from pagemenot.config import settings
from pagemenot.knowledge.rag import ingest_all
from pagemenot.slack_bot import create_slack_app, _chunk_text
from pagemenot.triage import run_triage, _executor, _dedup_key, _active_incidents, _dedup_lock

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pagemenot")

# dedup_key → jira issue key / pd incident url for open incidents; cleared on resolve
_active_jira_tickets: dict[tuple, str] = {}
_active_pd_incidents: dict[tuple, str] = {}
_jira_tickets_lock = asyncio.Lock()
_pd_incidents_lock = asyncio.Lock()

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


def _verify_hmac(secret: str, body: bytes, sig_header: str, prefix: str = "") -> bool:
    """Constant-time HMAC-SHA256 verification."""
    sig = sig_header.removeprefix(prefix)
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


async def _check_sig(
    provider: str,
    secret: Optional[str],
    body: bytes,
    sig_header: Optional[str],
    prefix: str = "",
) -> None:
    """Raise 401 if verification fails. Warn and pass if secret not configured."""
    if not secret:
        logger.warning("Webhook secret not set for %s — signature not verified", provider)
        return
    if not sig_header:
        raise HTTPException(status_code=401, detail="Missing signature header")
    # Take first value for multi-value headers (e.g. PagerDuty "v1=x,v1=y")
    first_sig = sig_header.split(",")[0].strip()
    if not _verify_hmac(secret, body, first_sig, prefix):
        raise HTTPException(status_code=401, detail="Signature mismatch")


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
    logger.info(f"   Exec: {'dry-run' if settings.pagemenot_exec_dry_run else 'enabled' if settings.pagemenot_exec_enabled else 'disabled'}")
    if settings.llm_provider != "ollama":
        if not settings.llm_external_enterprise_confirmed:
            raise RuntimeError(
                f"External LLM '{settings.llm_provider}' requires "
                f"LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true in .env. "
                f"Tool outputs (metrics, logs, diffs) will leave your network. "
                f"Only set this after confirming an enterprise/DPA agreement with your provider, "
                f"or switch to LLM_PROVIDER=ollama."
            )
        logger.warning(
            f"⚠️  External LLM ({settings.llm_provider}) active — "
            f"tool outputs leave your network. Ensure your enterprise DPA is in place."
        )
    logger.info("═" * 50)

    yield

    task.cancel()
    _executor.shutdown(wait=False)


app = FastAPI(title="Pagemenot", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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
@limiter.limit("60/minute")
async def pagerduty_webhook(
    request: Request,
    x_pagerduty_signature: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("pagerduty", settings.webhook_secret_pagerduty, body, x_pagerduty_signature, prefix="v1=")
    payload = await request.json()
    for msg in payload.get("messages", []):
        event = msg.get("event")
        if event == "incident.triggered":
            asyncio.create_task(_auto_triage("pagerduty", msg.get("incident", {})))
        elif event == "incident.resolved":
            asyncio.create_task(_handle_resolve("pagerduty", msg.get("incident", {})))
    return {"status": "accepted"}


@app.post("/webhooks/grafana")
@limiter.limit("60/minute")
async def grafana_webhook(
    request: Request,
    x_grafana_signature: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("grafana", settings.webhook_secret_grafana, body, x_grafana_signature)
    payload = await request.json()
    # Only triage firing alerts — skip resolved/ok state webhooks
    if payload.get("status") == "firing":
        asyncio.create_task(_auto_triage("grafana", payload))
    return {"status": "accepted"}


@app.post("/webhooks/alertmanager")
@limiter.limit("60/minute")
async def alertmanager_webhook(
    request: Request,
    x_alertmanager_token: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("alertmanager", settings.webhook_secret_alertmanager, body, x_alertmanager_token)
    payload = await request.json()
    for alert in payload.get("alerts", []):
        status = alert.get("status")
        if status == "firing":
            asyncio.create_task(_auto_triage("alertmanager", alert))
        elif status == "resolved":
            asyncio.create_task(_handle_resolve("alertmanager", alert))
    return {"status": "accepted"}


@app.post("/webhooks/generic")
@limiter.limit("60/minute")
async def generic_webhook(
    request: Request,
    x_pagemenot_signature: Optional[str] = Header(default=None),
):
    """Catch-all for any alert source. Just POST JSON with a 'title' or 'message'."""
    body = await request.body()
    await _check_sig("generic", settings.webhook_secret_generic, body, x_pagemenot_signature, prefix="sha256=")
    payload = await request.json()
    asyncio.create_task(_auto_triage("generic", payload))
    return {"status": "accepted"}


@app.post("/webhooks/opsgenie")
@limiter.limit("60/minute")
async def opsgenie_webhook(
    request: Request,
    x_og_hash: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("opsgenie", settings.webhook_secret_opsgenie, body, x_og_hash)
    payload = await request.json()
    # OpsGenie sends action + alert fields
    if payload.get("action") in ("Create", "Acknowledge") and payload.get("alert"):
        asyncio.create_task(_auto_triage("opsgenie", payload["alert"]))
    return {"status": "accepted"}


@app.post("/webhooks/datadog")
@limiter.limit("60/minute")
async def datadog_webhook(
    request: Request,
    x_datadog_signature: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("datadog", settings.webhook_secret_datadog, body, x_datadog_signature)
    payload = await request.json()
    if payload.get("alert_type") != "success":  # skip recoveries
        asyncio.create_task(_auto_triage("datadog", payload))
    return {"status": "accepted"}


@app.post("/webhooks/newrelic")
@limiter.limit("60/minute")
async def newrelic_webhook(
    request: Request,
    x_nr_webhook_token: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("newrelic", settings.webhook_secret_newrelic, body, x_nr_webhook_token)
    payload = await request.json()
    # Only triage open incidents — skip acknowledged/closed states
    if payload.get("state", "open") == "open":
        asyncio.create_task(_auto_triage("newrelic", payload))
    return {"status": "accepted"}


async def _page_pagerduty(result) -> Optional[str]:
    """Create a PagerDuty incident to page the on-call human. Returns incident URL or None."""
    if not settings.pagerduty_api_key:
        return None
    import httpx

    # Resolve the requester email (explicit config takes priority)
    from_email = settings.pagerduty_from_email
    if not from_email:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.pagerduty.com/users?limit=1",
                    headers={
                        "Authorization": f"Token token={settings.pagerduty_api_key}",
                        "Accept": "application/vnd.pagerduty+json;version=2",
                    },
                )
                from_email = r.json()["users"][0]["email"] if r.status_code == 200 else None
        except Exception:
            from_email = None

    if not from_email:
        logger.warning("PagerDuty escalation skipped — could not resolve requester email")
        return None

    # Fetch default service id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.pagerduty.com/services?limit=1",
                headers={
                    "Authorization": f"Token token={settings.pagerduty_api_key}",
                    "Accept": "application/vnd.pagerduty+json;version=2",
                },
            )
            service_id = r.json()["services"][0]["id"] if r.status_code == 200 else None
    except Exception:
        service_id = None

    if not service_id:
        logger.warning("PagerDuty escalation skipped — no service found")
        return None

    urgency = "high" if result.severity == "critical" else "low"
    body = {
        "incident": {
            "type": "incident",
            "title": f"{result.alert_title} ({result.service})",
            "service": {"id": service_id, "type": "service_reference"},
            "urgency": urgency,
            "body": {
                "type": "incident_body",
                "details": (
                    f"pagemenot could not auto-resolve this incident.\n\n"
                    f"Root cause: {result.root_cause}\n"
                    f"Confidence: {result.confidence}\n"
                    f"Triage duration: {result.duration_seconds:.1f}s"
                ),
            },
        }
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.pagerduty.com/incidents",
                json=body,
                headers={
                    "Authorization": f"Token token={settings.pagerduty_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/vnd.pagerduty+json;version=2",
                    "From": from_email,
                },
            )
        if resp.status_code in (200, 201):
            inc = resp.json()["incident"]
            url = inc["html_url"]
            logger.info("PagerDuty incident created: %s", url)
            return url
        logger.warning("PagerDuty incident creation failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("PagerDuty escalation error: %s", e)
    return None


async def _open_jira_ticket(result) -> Optional[tuple[str, str]]:
    """Create a Jira SM service request. Returns (issue_key, browser_url) or None on failure."""
    if not (settings.jira_sm_url and settings.jira_sm_email and
            settings.jira_sm_api_token and settings.jira_sm_project_key):
        return None
    import httpx

    base = settings.jira_sm_url.rstrip("/")
    credentials = base64.b64encode(
        f"{settings.jira_sm_email}:{settings.jira_sm_api_token}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-ExperimentalApi": "opt-in",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Resolve service desk ID
            sd_id = settings.jira_sm_service_desk_id
            if not sd_id:
                r = await client.get(f"{base}/rest/servicedeskapi/servicedesk", headers=headers)
                for sd in r.json().get("values", []):
                    if sd.get("projectKey") == settings.jira_sm_project_key:
                        sd_id = str(sd["id"])
                        break

            if not sd_id:
                logger.warning("Jira SM: service desk not found for project %s", settings.jira_sm_project_key)
                return None

            # Resolve request type ID
            rt_id = settings.jira_sm_request_type_id
            if not rt_id:
                r = await client.get(
                    f"{base}/rest/servicedeskapi/servicedesk/{sd_id}/requesttype", headers=headers
                )
                types = r.json().get("values", [])
                if types:
                    rt_id = str(types[0]["id"])

            if not rt_id:
                logger.warning("Jira SM: no request types found for service desk %s", sd_id)
                return None

            # Create the request
            resp = await client.post(
                f"{base}/rest/servicedeskapi/request",
                headers=headers,
                json={
                    "serviceDeskId": sd_id,
                    "requestTypeId": rt_id,
                    "requestFieldValues": {
                        "summary": f"INCIDENT: {result.alert_title} ({result.service})",
                        "description": (
                            f"Alert: {result.alert_title}\n"
                            f"Service: {result.service}\n"
                            f"Severity: {result.severity}\n\n"
                            f"Root cause: {result.root_cause}\n\n"
                            f"Triage confidence: {result.confidence}"
                        ),
                    },
                },
            )

        if resp.status_code in (200, 201):
            issue_key = resp.json().get("issueKey", "")
            url = f"{base}/browse/{issue_key}"
            logger.info("Jira ticket created: %s", url)
            return (issue_key, url)
        logger.warning("Jira ticket creation failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Jira ticket creation error: %s", e)
    return None



async def _close_jira_ticket(issue_key: str, comment: str) -> bool:
    """Add a resolution comment and transition a Jira issue to Done/Resolved/Closed."""
    if not (settings.jira_sm_url and settings.jira_sm_email and settings.jira_sm_api_token):
        return False
    import httpx

    base = settings.jira_sm_url.rstrip("/")
    credentials = base64.b64encode(
        f"{settings.jira_sm_email}:{settings.jira_sm_api_token}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{base}/rest/api/3/issue/{issue_key}/comment",
                headers=headers,
                json={"body": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": comment}]}
                ]}},
            )
            r = await client.get(
                f"{base}/rest/api/3/issue/{issue_key}/transitions", headers=headers
            )
            transitions = r.json().get("transitions", [])
            _close_names = {"done", "resolved", "closed", "complete"}
            transition_id = next(
                (t["id"] for t in transitions if t.get("name", "").lower() in _close_names),
                None,
            )
            if not transition_id:
                logger.warning(
                    "Jira %s: no close transition found (available: %s)",
                    issue_key,
                    [t.get("name") for t in transitions],
                )
                return False
            await client.post(
                f"{base}/rest/api/3/issue/{issue_key}/transitions",
                headers=headers,
                json={"transition": {"id": transition_id}},
            )
            logger.info("Jira ticket %s closed via transition %s", issue_key, transition_id)
            return True
    except Exception as e:
        logger.warning("Jira close error for %s: %s", issue_key, e)
    return False


async def _handle_resolve(source: str, payload: dict) -> None:
    """Handle a monitoring-system resolve event: clear dedup registry and close any open Jira ticket."""
    from pagemenot.triage import _parse_alert
    from pagemenot.slack_bot import get_client

    try:
        parsed = _parse_alert(source, payload)
    except Exception as e:
        logger.warning("_handle_resolve: could not parse %s payload: %s", source, e)
        return

    key = _dedup_key(parsed["service"], parsed["title"])

    # Peek at issue_key without removing yet — only remove after successful close
    async with _jira_tickets_lock:
        issue_key = _active_jira_tickets.get(key)

    async with _pd_incidents_lock:
        _active_pd_incidents.pop(key, None)

    # Clear dedup registry so future occurrences trigger fresh triage
    with _dedup_lock:
        _active_incidents.pop(key, None)

    if not issue_key:
        return

    comment = (
        f"Alert resolved by {source}. Service: {parsed['service']}. "
        "Closing automatically — no further action required."
    )
    closed = await _close_jira_ticket(issue_key, comment)

    client = get_client()
    channel = settings.pagemenot_channel
    if closed:
        async with _jira_tickets_lock:
            _active_jira_tickets.pop(key, None)
        await client.chat_postMessage(
            channel=channel,
            text=f"✅ *{parsed['title']}* resolved — Jira {issue_key} closed automatically.",
        )
    else:
        await client.chat_postMessage(
            channel=channel,
            text=f"✅ *{parsed['title']}* resolved — could not close Jira {issue_key} automatically.",
        )

async def _auto_triage(source: str, payload: dict):
    """Run triage and post all updates to Slack in a thread."""
    import uuid
    from pagemenot.slack_bot import get_client, _approval_store
    from pagemenot.triage import _parse_alert

    client = get_client()
    channel = settings.pagemenot_channel
    thread_ts: Optional[str] = None

    try:
        # Step 1: post alert immediately so Slack shows it before crew starts
        parsed = _parse_alert(source, payload)
        sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(parsed.get("severity", ""), "⚪")
        alert_title = parsed.get("title", "Unknown alert")
        service = parsed.get("service", "unknown")

        main_resp = await client.chat_postMessage(
            channel=channel,
            text=f"{sev_icon} *{alert_title}* — `{service}`",
        )
        thread_ts = main_resp["ts"]

        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="🔍 Crew is investigating...",
        )

    except Exception as e:
        logger.error("Failed to post alert to Slack: %s", e, exc_info=True)

    # Step 2: run triage (may take several minutes)
    try:
        result = await run_triage(source=source, payload=payload)
    except Exception as e:
        logger.error("Triage crew crashed: %s", e, exc_info=True)
        if thread_ts:
            try:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"⚠️ Triage failed — crew error: `{e}`\nManual review required.",
                )
            except Exception:
                pass
        return

    # Step 3: post result in thread
    try:
        if result.suppressed:
            sev_label = "Low-severity" if result.severity == "low" else "Duplicate"
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"⚪ {sev_label} — suppressed (no action taken)",
            )
            return

        dry = settings.pagemenot_exec_dry_run
        sev = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(result.severity, "⚪")
        conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")

        if result.resolved_automatically:
            log_text = "\n".join(result.execution_log) if result.execution_log else "No steps logged."
            verb = "Would resolve" if dry else "Auto-resolved"
            icon = "🔵" if dry else "✅"
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"{icon} *{verb}* ⏱️ {result.duration_seconds:.1f}s\n\n"
                    f"*Root cause:* {result.root_cause}\n\n"
                    f"*{'Steps (dry run)' if dry else 'Steps executed'}:*\n{log_text}"
                ),
            )
        else:
            # Crew has a plan if it found remediation steps that don't require human approval
            can_resolve = bool(result.remediation_steps) and not bool(result.needs_approval)
            # Only escalate high/critical when crew has no resolution path
            needs_page = result.severity in ("critical", "high") and not can_resolve

            if can_resolve:
                status_line = "⚠️ Not auto-resolved — crew has remediation steps (exec disabled or dry-run)"
            elif needs_page:
                status_line = "🚨 *Could not resolve — escalating*"
            else:
                status_line = "⚠️ No runbook match"

            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"{status_line} | ⏱️ {result.duration_seconds:.1f}s\n\n"
                    f"*Root cause* ({conf} {result.confidence}): {result.root_cause}"
                ),
            )

            if result.raw_output:
                for i, chunk in enumerate(_chunk_text(result.raw_output, 2900)[:3]):
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"Analysis (part {i + 1})\n```{chunk}```",
                    )

            # Approval buttons for steps that need human sign-off
            if result.needs_approval and settings.pagemenot_approval_gate:
                approval_id = str(uuid.uuid4())[:8]
                await _approval_store.set(approval_id, {
                    "steps": result.needs_approval,
                    "service": result.service or "",
                })
                approval_text = "\n".join(f"• `{a}`" for a in result.needs_approval)
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="Actions requiring approval",
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"*⚠️ Steps requiring approval:*\n{approval_text}"},
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "✅ Approve & Execute"},
                                    "action_id": "approve_action",
                                    "value": approval_id,
                                    "style": "primary",
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "❌ Reject"},
                                    "action_id": "reject_action",
                                    "value": approval_id,
                                    "style": "danger",
                                },
                            ],
                        },
                    ],
                )

            if needs_page:
                dedup_key = _dedup_key(result.service, result.alert_title)
                async with _jira_tickets_lock:
                    existing_jira = _active_jira_tickets.get(dedup_key)
                async with _pd_incidents_lock:
                    existing_pd = _active_pd_incidents.get(dedup_key)

                # Jira: open once per incident lifecycle
                if existing_jira:
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"🎫 Jira already open: {settings.jira_sm_url.rstrip('/')}/browse/{existing_jira}",
                    )
                else:
                    jira_info = await _open_jira_ticket(result)
                    if isinstance(jira_info, tuple):
                        issue_key, jira_url = jira_info
                        async with _jira_tickets_lock:
                            _active_jira_tickets[dedup_key] = issue_key
                        await client.chat_postMessage(
                            channel=channel, thread_ts=thread_ts, text=f"🎫 Jira: {jira_url}",
                        )

                # PagerDuty: page once per incident lifecycle
                new_pd_url: Optional[str] = None
                if existing_pd:
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"📟 PagerDuty already paged: {existing_pd}",
                    )
                else:
                    pd_result = await _page_pagerduty(result)
                    if isinstance(pd_result, str):
                        new_pd_url = pd_result
                        async with _pd_incidents_lock:
                            _active_pd_incidents[dedup_key] = new_pd_url
                        await client.chat_postMessage(
                            channel=channel, thread_ts=thread_ts, text=f"📟 PagerDuty: {new_pd_url}",
                        )

                # Only ping oncall channel on first escalation of this incident
                escalation_channel = settings.pagemenot_oncall_channel
                if escalation_channel and not (existing_jira and existing_pd):
                    effective_pd = existing_pd or new_pd_url
                    pd_line = f"\n📟 {effective_pd}" if effective_pd else ""
                    await client.chat_postMessage(
                        channel=escalation_channel,
                        text=(
                            f"{sev} *ESCALATION:* {result.alert_title} ({result.service})\n"
                            f"Confidence: {conf} {result.confidence} — crew could not resolve — "
                            f"see #{channel}{pd_line}"
                        ),
                    )

        if result.postmortem_path and not result.pending_review:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"📝 Postmortem saved: `knowledge/postmortems/{result.postmortem_path}`",
            )
        elif result.postmortem_path and result.pending_review:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"📋 Postmortem draft needs review (medium confidence): "
                    f"`knowledge/pending_review/{result.postmortem_path}`"
                ),
            )

    except Exception as e:
        logger.error("Failed to post triage result to Slack: %s", e, exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pagemenot.main:app", host="0.0.0.0", port=8080, log_level="info")
