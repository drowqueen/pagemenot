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
from pagemenot.rag import ingest_all
from pagemenot.slack_bot import create_slack_app, _chunk_text, _verif_store
from pagemenot.triage import run_triage, _executor, _parse_alert, _clear_dedup

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pagemenot")

limiter = Limiter(
    key_func=get_remote_address, default_limits=[settings.pagemenot_webhook_rate_limit]
)


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

    # Wire CW verification callback into slack_bot (avoids circular import)
    import pagemenot.slack_bot as _sbot

    def _schedule_verification(
        alarm_name, region, channel, thread_ts, jira_url, pd_url, entry, approved_by
    ):
        from pagemenot.slack_bot import get_client as _gc
        from pagemenot.triage import TriageResult as _TR

        _r = _TR(
            alert_title=entry.get("alert_title", ""),
            service=entry.get("service", ""),
            severity=entry.get("severity", "unknown"),
            root_cause=entry.get("root_cause", ""),
            alarm_name=alarm_name,
            region=region,
        )
        # Persist before launching — survives container restart
        asyncio.create_task(
            _verif_store.set(
                alarm_name,
                {
                    "alarm_name": alarm_name,
                    "region": region,
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "jira_url": jira_url,
                    "pd_url": pd_url,
                    "approved_by": approved_by,
                    "alert_title": entry.get("alert_title", ""),
                    "service": entry.get("service", ""),
                    "severity": entry.get("severity", "unknown"),
                    "root_cause": entry.get("root_cause", ""),
                },
                ttl=settings.pagemenot_verify_timeout + 300,
            )
        )
        asyncio.create_task(
            _verify_cw_recovery(
                alarm_name, region, channel, thread_ts, _gc(), _r, jira_url, pd_url, approved_by
            )
        )

    _sbot._post_verification_task = _schedule_verification

    # Resume any CW verifications that were in-flight when the container last stopped
    _pending = await _verif_store.get_all()
    if _pending:
        logger.info("Resuming %d pending CW verification(s) from last run", len(_pending))
        from pagemenot.slack_bot import get_client as _gc2
        from pagemenot.triage import TriageResult as _TR2

        for _pv in _pending.values():
            _pr = _TR2(
                alert_title=_pv.get("alert_title", ""),
                service=_pv.get("service", ""),
                severity=_pv.get("severity", "unknown"),
                root_cause=_pv.get("root_cause", ""),
                alarm_name=_pv.get("alarm_name", ""),
                region=_pv.get("region", ""),
            )
            asyncio.create_task(
                _verify_cw_recovery(
                    _pv["alarm_name"],
                    _pv.get("region", ""),
                    _pv["channel"],
                    _pv["thread_ts"],
                    _gc2(),
                    _pr,
                    _pv.get("jira_url", ""),
                    _pv.get("pd_url", ""),
                    _pv.get("approved_by", ""),
                )
            )

    logger.info("═" * 50)
    logger.info("🦞 Pagemenot is online")
    logger.info(f"   LLM: {settings.llm_provider}/{settings.llm_model}")
    logger.info(f"   Integrations: {settings.enabled_integrations or ['none — add via .env']}")
    logger.info(f"   Slack channel: #{settings.pagemenot_channel}")
    logger.info(
        f"   Exec: {'dry-run' if settings.pagemenot_exec_dry_run else 'enabled' if settings.pagemenot_exec_enabled else 'disabled'}"
    )
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

    # Periodically re-ingest knowledge base so human-written postmortems are picked up
    async def _reindex_loop():
        while True:
            await asyncio.sleep(3600)  # every hour
            try:
                await asyncio.get_running_loop().run_in_executor(None, ingest_all)
                logger.info("Knowledge base re-indexed")
            except Exception as e:
                logger.warning("Re-index failed: %s", e)

    reindex_task = asyncio.create_task(_reindex_loop())

    yield

    task.cancel()
    reindex_task.cancel()
    _executor.shutdown(wait=True)  # drain in-progress triages before exit


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
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def pagerduty_webhook(
    request: Request,
    x_pagerduty_signature: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig(
        "pagerduty", settings.webhook_secret_pagerduty, body, x_pagerduty_signature, prefix="v1="
    )
    payload = await request.json()
    for msg in payload.get("messages", []):
        # PagerDuty v2 webhook event type is "incident.triggered"
        if msg.get("event") == "incident.triggered":
            asyncio.create_task(_auto_triage("pagerduty", msg.get("incident", {})))
    return {"status": "accepted"}


@app.post("/webhooks/grafana")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
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
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def alertmanager_webhook(
    request: Request,
    x_alertmanager_token: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig(
        "alertmanager", settings.webhook_secret_alertmanager, body, x_alertmanager_token
    )
    payload = await request.json()
    for alert in payload.get("alerts", []):
        if alert.get("status") == "firing":
            asyncio.create_task(_auto_triage("alertmanager", alert))
    return {"status": "accepted"}


@app.post("/webhooks/generic")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def generic_webhook(
    request: Request,
    x_pagemenot_signature: Optional[str] = Header(default=None),
):
    """Catch-all for any alert source. Just POST JSON with a 'title' or 'message'."""
    body = await request.body()
    await _check_sig(
        "generic", settings.webhook_secret_generic, body, x_pagemenot_signature, prefix="sha256="
    )
    payload = await request.json()
    # Skip GCP Cloud Monitoring resolved notifications (state=closed)
    incident = payload.get("incident", {})
    if incident and incident.get("state") == "closed":
        parsed = _parse_alert("generic", payload)
        _clear_dedup(parsed["service"], parsed["title"])
        return {"status": "skipped", "reason": "incident closed"}
    asyncio.create_task(_auto_triage("generic", payload))
    return {"status": "accepted"}


@app.post("/webhooks/sns")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def sns_webhook(
    request: Request,
    x_amz_sns_message_type: Optional[str] = Header(default=None),
):
    """AWS SNS endpoint — handles CloudWatch alarm notifications and subscription confirmation."""
    import httpx

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg_type = x_amz_sns_message_type or payload.get("Type", "")

    if msg_type == "SubscriptionConfirmation":
        url = payload.get("SubscribeURL")
        if url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.get(url)
                logger.info("SNS subscription confirmed")
            except Exception as e:
                logger.warning("SNS subscription confirmation failed: %s", e)
        return {"status": "confirmed"}

    if msg_type == "Notification":
        import json as _json

        message_str = payload.get("Message", "{}")
        try:
            message = _json.loads(message_str)
        except Exception:
            message = {"detail": message_str}

        new_state = message.get("NewStateValue", "")
        alarm_name = message.get("AlarmName", "CloudWatch Alarm")
        region = message.get("Region", "")
        trigger = message.get("Trigger", {})
        metric = trigger.get("MetricName", "")
        dim_list = trigger.get("Dimensions", [])
        dims = {d["name"]: d["value"] for d in dim_list}
        # Use the last (most specific) dimension value; fall back to alarm name.
        # Avoids hardcoding AWS dimension names — works for any service/namespace.
        dim_values = [d["value"] for d in dim_list]
        service = dim_values[-1] if dim_values else alarm_name

        # Extract severity from alarm description (e.g. "severity: critical")
        import re as _re

        alarm_desc = message.get("AlarmDescription") or ""
        _sev_match = _re.search(r"\bseverity\s*:\s*(\w+)", alarm_desc, _re.IGNORECASE)
        alarm_severity = _sev_match.group(1).lower() if _sev_match else "high"

        if new_state == "OK":
            from pagemenot.slack_bot import get_client as _gc

            _client = _gc()

            # If a pending CW verification exists (approval path), claim it atomically
            pv = await _verif_store.pop(alarm_name)
            if pv:
                try:
                    await _client.chat_postMessage(
                        channel=pv["channel"],
                        thread_ts=pv["thread_ts"],
                        text=f"✅ *Verified healthy* — `{alarm_name}` back to OK.",
                    )
                except Exception as e:
                    logger.warning("SNS OK: approval thread notify failed: %s", e)
                # Jira/PD resolved below via _alarm_incidents (if tracked)

            entry = _alarm_incidents.pop(alarm_name, None)
            if entry:
                asyncio.create_task(
                    _resolve_jira_ticket(
                        entry["jira_url"], resolution_note="CloudWatch alarm recovered"
                    )
                )
                asyncio.create_task(
                    _resolve_pagerduty_incident(entry["pd_url"], resolved_by="cloudwatch")
                )
                try:
                    await _client.chat_postMessage(
                        channel=entry["channel"],
                        thread_ts=entry["thread_ts"],
                        text=f"✅ *Recovered:* `{alarm_name}` — CloudWatch alarm back to OK. Jira closed, PD resolved.",
                    )
                except Exception as e:
                    logger.warning("SNS OK: Slack notify failed: %s", e)
            else:
                logger.info("SNS OK for '%s' — no tracked incident to close", alarm_name)
            return {"status": "recovered"}

        if new_state != "ALARM":
            return {"status": "ignored", "state": new_state}

        triage_payload = {
            "title": alarm_name,
            "alarm_name": alarm_name,
            "message": message.get("NewStateReason", ""),
            "service": service,
            "severity": alarm_severity,
            "region": region,
            "metric": metric,
            "dimensions": dims,
            "source": "cloudwatch",
        }
        asyncio.create_task(_auto_triage("sns", triage_payload))
        return {"status": "accepted"}

    return {"status": "ignored"}


@app.post("/webhooks/opsgenie")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
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
@limiter.limit(settings.pagemenot_webhook_rate_limit)
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
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def newrelic_webhook(
    request: Request,
    x_nr_webhook_token: Optional[str] = Header(default=None),
):
    body = await request.body()
    await _check_sig("newrelic", settings.webhook_secret_newrelic, body, x_nr_webhook_token)
    payload = await request.json()
    # Only triage open incidents — skip acknowledged/closed states
    # current_state = NR legacy ("open"/"acknowledged"/"closed")
    # state = NR One ("CREATED"/"ACKNOWLEDGED"/"CLOSED")
    incident_state = payload.get("current_state", payload.get("state", "open")).lower()
    if incident_state not in ("closed", "acknowledged"):
        asyncio.create_task(_auto_triage("newrelic", payload))
    return {"status": "accepted"}


async def _post_resolved_to_slack(title: str, source: str, resolved_by: str = ""):
    """Post a resolved banner to the alerts channel when a human closes PD/Jira."""
    from pagemenot.slack_bot import _client

    if not _client:
        return
    detail = f"Closed by {resolved_by} on {source}." if resolved_by else f"Closed on {source}."
    try:
        await _client.chat_postMessage(
            channel=settings.pagemenot_channel,
            text=f"🟢 *Resolved ({source}):* {title}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🟢 *Resolved ({source}):* {title}\n_{detail}_",
                    },
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to post resolve notification to Slack: {e}")


@app.post("/webhooks/pagerduty/resolve")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def pagerduty_resolve_webhook(
    request: Request,
    x_pagerduty_signature: Optional[str] = Header(default=None),
):
    """Receives PagerDuty incident.resolve events and posts resolved banner to Slack."""
    body = await request.body()
    await _check_sig(
        "pagerduty", settings.webhook_secret_pagerduty, body, x_pagerduty_signature, prefix="v1="
    )
    payload = await request.json()
    for msg in payload.get("messages", []):
        event = msg.get("event", "")
        if event in ("incident.resolve", "incident.resolved"):
            incident = msg.get("incident", {})
            title = incident.get("title", incident.get("description", "Unknown incident"))
            resolved_by = ""
            if incident.get("resolved_by"):
                resolved_by = incident["resolved_by"].get("summary", "")
            asyncio.create_task(_post_resolved_to_slack(title, "PagerDuty", resolved_by))
    return {"status": "accepted"}


@app.post("/webhooks/jira")
@limiter.limit(settings.pagemenot_webhook_rate_limit)
async def jira_webhook(
    request: Request,
    x_atlassian_token: Optional[str] = Header(default=None),
):
    """Receives Jira issue webhooks. Posts resolved banner when issue transitions to Done/Resolved."""
    body = await request.body()
    await _check_sig("jira", settings.webhook_secret_jira, body, x_atlassian_token)
    payload = await request.json()
    issue = payload.get("issue", {})
    status = issue.get("fields", {}).get("status", {}).get("name", "")
    _done = {s.strip().lower() for s in settings.jira_done_statuses.split(",")}
    if status.lower() in _done:
        title = issue.get("fields", {}).get("summary", issue.get("key", "Unknown issue"))
        resolved_by = payload.get("user", {}).get("displayName", "")
        asyncio.create_task(_post_resolved_to_slack(title, "Jira", resolved_by))
    return {"status": "accepted"}


async def _page_pagerduty(result) -> Optional[str]:
    """Create a PagerDuty incident to page the on-call human. Returns incident URL or None."""
    if not settings.pagerduty_api_key:
        return None
    import httpx

    # Resolve the requester: fetch first user from account
    try:
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
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
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
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
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
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
        logger.warning(
            "PagerDuty incident creation failed: %s %s", resp.status_code, resp.text[:200]
        )
    except Exception as e:
        logger.warning("PagerDuty escalation error: %s", e)
    return None


async def _open_jira_ticket(result) -> Optional[str]:
    """Create a Jira SM service request. Returns the browser URL or None on failure."""
    if not (
        settings.jira_sm_url
        and settings.jira_sm_email
        and settings.jira_sm_api_token
        and settings.jira_sm_project_key
    ):
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
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
            # Resolve service desk ID
            sd_id = settings.jira_sm_service_desk_id
            if not sd_id:
                r = await client.get(f"{base}/rest/servicedeskapi/servicedesk", headers=headers)
                for sd in r.json().get("values", []):
                    if sd.get("projectKey") == settings.jira_sm_project_key:
                        sd_id = str(sd["id"])
                        break

            if not sd_id:
                logger.warning(
                    "Jira SM: service desk not found for project %s", settings.jira_sm_project_key
                )
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
            return url
        logger.warning("Jira ticket creation failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Jira ticket creation error: %s", e)
    return None


async def _resolve_jira_ticket(jira_url: str, resolution_note: str = "") -> None:
    """Transition Jira ticket to Done."""
    if not (
        jira_url and settings.jira_sm_url and settings.jira_sm_email and settings.jira_sm_api_token
    ):
        return
    import httpx
    import re

    m = re.search(r"/browse/([A-Z]+-\d+)", jira_url)
    if not m:
        logger.warning("Jira resolve: could not extract issue key from %s", jira_url)
        return
    key = m.group(1)
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
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
            r = await client.get(f"{base}/rest/api/2/issue/{key}/transitions", headers=headers)
            transitions = r.json().get("transitions", [])
            _done_keywords = {s.strip().lower() for s in settings.jira_done_statuses.split(",")}
            done_id = next(
                (
                    t["id"]
                    for t in transitions
                    if any(kw in t["name"].lower() for kw in _done_keywords)
                ),
                None,
            )
            if not done_id:
                logger.warning("Jira resolve: no Done/Resolved transition found for %s", key)
                return
            body: dict = {"transition": {"id": done_id}}
            if resolution_note:
                body["update"] = {"comment": [{"add": {"body": resolution_note}}]}
            resp = await client.post(
                f"{base}/rest/api/2/issue/{key}/transitions", headers=headers, json=body
            )
        if resp.status_code in (200, 204):
            logger.info("Jira ticket resolved: %s", key)
        else:
            logger.warning("Jira resolve failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Jira resolve error: %s", e)


async def _resolve_pagerduty_incident(pd_url: str, resolved_by: str = "") -> None:
    """Resolve PagerDuty incident."""
    if not (pd_url and settings.pagerduty_api_key):
        return
    import httpx
    import re

    m = re.search(r"/incidents/([A-Z0-9]+)", pd_url)
    if not m:
        logger.warning("PD resolve: could not extract incident ID from %s", pd_url)
        return
    inc_id = m.group(1)
    from_email = settings.pagerduty_from_email
    if not from_email:
        try:
            async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
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
        logger.warning("PD resolve skipped — no from email")
        return
    try:
        async with httpx.AsyncClient(timeout=settings.pagemenot_http_timeout) as client:
            resp = await client.put(
                f"https://api.pagerduty.com/incidents/{inc_id}",
                headers={
                    "Authorization": f"Token token={settings.pagerduty_api_key}",
                    "Accept": "application/vnd.pagerduty+json;version=2",
                    "Content-Type": "application/json",
                    "From": from_email,
                },
                json={"incident": {"type": "incident_reference", "status": "resolved"}},
            )
        if resp.status_code in (200, 201):
            logger.info("PagerDuty incident resolved: %s", inc_id)
        else:
            logger.warning("PD resolve failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("PD resolve error: %s", e)


# alarm_name → {jira_url, pd_url, channel, thread_ts} — populated for SNS/CloudWatch alarms
_alarm_incidents: dict[str, dict] = {}


async def _verify_cw_recovery(
    alarm_name: str,
    region: str,
    channel: str,
    thread_ts: str,
    client,
    result,
    jira_url: str = "",
    pd_url: str = "",
    approved_by: str = "",
) -> None:
    """Poll CW alarm until OK or timeout. Works for any AWS service type."""
    import boto3

    timeout = settings.pagemenot_verify_timeout
    poll = settings.pagemenot_verify_poll_interval
    elapsed = 0
    import re as _re

    cw_kwargs = {}
    # SNS Region field is human-readable (e.g. "EU (Ireland)") — only use API-format codes
    _api_region = region if region and _re.match(r"^[a-z]+-[a-z]+-\d$", region) else None
    if _api_region:
        cw_kwargs["region_name"] = _api_region
    elif settings.aws_region:
        cw_kwargs["region_name"] = settings.aws_region
    cw = boto3.client("cloudwatch", **cw_kwargs)
    loop = asyncio.get_running_loop()
    logger.info("CW verify started: %s (timeout=%ds, poll=%ds)", alarm_name, timeout, poll)

    while elapsed < timeout:
        await asyncio.sleep(poll)
        elapsed += poll
        try:
            resp = await loop.run_in_executor(
                _executor, lambda: cw.describe_alarms(AlarmNames=[alarm_name])
            )
            alarms = resp.get("MetricAlarms", []) + resp.get("CompositeAlarms", [])
            state = alarms[0].get("StateValue") if alarms else "NO_ALARM"
            logger.info("CW verify poll [%ds]: %s → %s", elapsed, alarm_name, state)
            if alarms and alarms[0].get("StateValue") == "OK":
                # Claim the pending verification — prevents SNS OK handler from double-posting
                await _verif_store.pop(alarm_name)
                resolved_by = f"human-approved by <@{approved_by}>" if approved_by else "runbook"
                links = []
                if jira_url:
                    links.append(f"🎫 <{jira_url}|Jira closed>")
                    asyncio.create_task(
                        _resolve_jira_ticket(
                            jira_url, f"Auto-resolved — verified healthy ({resolved_by})"
                        )
                    )
                if pd_url:
                    links.append("📟 PD resolved")
                    asyncio.create_task(
                        _resolve_pagerduty_incident(pd_url, resolved_by=approved_by or "pagemenot")
                    )
                suffix = "  •  " + "  •  ".join(links) if links else ""
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"✅ *Verified healthy* — `{alarm_name}` back to OK after {elapsed}s.{suffix}",
                )
                from pagemenot.rag import write_and_index_postmortem as _wip

                loop.run_in_executor(None, _wip, result, approved_by or "agent", jira_url)
                logger.info("CW verified OK: %s after %ds", alarm_name, elapsed)
                return
        except Exception as e:
            logger.warning("CW verify poll failed for %s: %s", alarm_name, e)

    # Timeout — runbook did not resolve the incident
    await _verif_store.pop(alarm_name)
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"❌ *Recovery not confirmed:* `{alarm_name}` still in ALARM after {timeout}s. Escalating.",
    )
    logger.warning("CW verify timeout: %s after %ds", alarm_name, timeout)
    _SEV = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    sev_rank = _SEV.get(result.severity, 0)
    if not jira_url:
        jira_min = _SEV.get(settings.pagemenot_jira_min_severity, 0)
        if sev_rank >= jira_min:
            jira_url = await _open_jira_ticket(result) or ""
            if jira_url:
                await client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts, text=f"🎫 Jira: {jira_url}"
                )
    if not pd_url:
        pd_min = _SEV.get(settings.pagemenot_pd_min_severity, 2)
        if sev_rank >= pd_min:
            pd_url = await _page_pagerduty(result) or ""
            if pd_url:
                await client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts, text=f"📟 PagerDuty: {pd_url}"
                )
    if settings.pagemenot_oncall_channel:
        pd_min = _SEV.get(settings.pagemenot_pd_min_severity, 2)
        if sev_rank >= pd_min:
            sev = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(result.severity, "⚪")
            await client.chat_postMessage(
                channel=settings.pagemenot_oncall_channel,
                text=f"{sev} *ESCALATION:* {result.alert_title} ({result.service}) — runbook ran but `{alarm_name}` did not recover after {timeout}s.",
            )
    from pagemenot.rag import write_and_index_postmortem as _wip

    asyncio.get_running_loop().run_in_executor(None, _wip, result, approved_by or "agent", jira_url)


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
            dry = settings.pagemenot_exec_dry_run
            verifying = not dry and bool(result.alarm_name)
            log_text = (
                "\n\n".join(result.execution_log[:10])
                if result.execution_log
                else "No steps logged."
            )
            icon = "🔵" if dry else "⏳" if verifying else "🟢"
            label = (
                "Dry-run resolved" if dry else "Runbook executed" if verifying else "Auto-resolved"
            )
            status_line = (
                f"_Monitoring `{result.alarm_name}` — will confirm healthy when alarm returns to OK..._"
                if verifying
                else ("_Dry run — no real changes made._" if dry else "_Steps completed._")
            )
            resp = await client.chat_postMessage(
                channel=channel,
                text=f"{icon} *{label}:* {result.alert_title}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{icon} *{label}:* {result.alert_title}\n"
                            f"_Service: {result.service} | ⏱️ {result.duration_seconds:.0f}s_",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Runbook execution:*\n\n{log_text[:2800]}",
                        },
                    },
                    {"type": "section", "text": {"type": "mrkdwn", "text": status_line}},
                ],
            )
            if verifying:
                asyncio.create_task(
                    _verify_cw_recovery(
                        result.alarm_name, result.region, channel, resp["ts"], client, result
                    )
                )
            else:
                from pagemenot.rag import write_and_index_postmortem as _wip

                asyncio.get_running_loop().run_in_executor(None, _wip, result, "agent", "")
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
            clean = (
                result.raw_output.replace("```sh\n", "")
                .replace("```bash\n", "")
                .replace("```\n", "")
                .replace("```", "")
            )
            for i, chunk in enumerate(
                _chunk_text(clean, settings.pagemenot_slack_chunk_size)[
                    : settings.pagemenot_slack_max_chunks
                ]
            ):
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"Analysis (part {i + 1})",
                    blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}],
                )

        if result.execution_log:
            exec_text = "\n\n".join(result.execution_log[:10])
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread,
                text="Runbook execution",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Runbook execution:*\n\n{exec_text[:2800]}",
                        },
                    }
                ],
            )

        # Open Jira SM ticket + page PagerDuty first — so urls are available for the approval entry
        _SEV = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        sev_rank = _SEV.get(result.severity, 0)
        jira_url = pd_url = None
        if not settings.pagemenot_exec_dry_run and not result.resolved_automatically:
            jira_min = _SEV.get(settings.pagemenot_jira_min_severity, 2)
            pd_min = _SEV.get(settings.pagemenot_pd_min_severity, 2)
            tasks = [
                _open_jira_ticket(result) if sev_rank >= jira_min else asyncio.sleep(0),
                _page_pagerduty(result) if sev_rank >= pd_min else asyncio.sleep(0),
            ]
            jira_url, pd_url = await asyncio.gather(*tasks, return_exceptions=True)
            if isinstance(jira_url, str):
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"🎫 Jira ticket opened: {jira_url}",
                )
            if isinstance(pd_url, str):
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"📟 On-call paged via PagerDuty: {pd_url}",
                )

        # Track alarm → Jira/PD URLs for CloudWatch OK recovery
        if source == "sns" and payload.get("alarm_name"):
            _alarm_incidents[payload["alarm_name"]] = {
                "jira_url": jira_url if isinstance(jira_url, str) else "",
                "pd_url": pd_url if isinstance(pd_url, str) else "",
                "channel": channel,
                "thread_ts": thread,
            }

        # Approval buttons — after Jira/PD so urls are stored in entry
        _approval_sev_min = _SEV.get(settings.pagemenot_approval_min_severity, 2)
        if (
            result.pending_exec_steps
            and settings.pagemenot_approval_gate
            and sev_rank >= _approval_sev_min
        ):
            from pagemenot.slack_bot import _approval_store
            import uuid as _uuid

            approval_id = str(_uuid.uuid4())[:8]
            await _approval_store.set(
                approval_id,
                {
                    "steps": result.pending_exec_steps,
                    "service": result.service or "",
                    "alert_title": result.alert_title or "",
                    "severity": result.severity or "high",
                    "root_cause": result.root_cause or "",
                    "jira_url": jira_url if isinstance(jira_url, str) else "",
                    "pd_url": pd_url if isinstance(pd_url, str) else "",
                    "similar_incidents": result.similar_incidents or [],
                    "alarm_name": result.alarm_name,
                    "region": result.region,
                },
            )
            steps_text = "\n".join(f"• `{s[:100]}`" for s in result.pending_exec_steps[:5])
            await client.chat_postMessage(
                channel=channel,
                text=f"⚠️ Approval required: {result.alert_title}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*⚠️ Approval required:* {result.alert_title}\n{steps_text}",
                        },
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

        # Acknowledge button — no runbook matched but LLM flagged manual steps; user confirms manual fix
        if (
            not result.pending_exec_steps
            and result.needs_approval
            and settings.pagemenot_approval_gate
            and sev_rank >= _approval_sev_min
        ):
            from pagemenot.slack_bot import _approval_store
            import uuid as _uuid

            ack_id = str(_uuid.uuid4())[:8]
            await _approval_store.set(
                ack_id,
                {
                    "steps": [],
                    "service": result.service or "",
                    "alert_title": result.alert_title or "",
                    "severity": result.severity or "high",
                    "root_cause": result.root_cause or "",
                    "jira_url": jira_url if isinstance(jira_url, str) else "",
                    "pd_url": pd_url if isinstance(pd_url, str) else "",
                    "similar_incidents": result.similar_incidents or [],
                    "alarm_name": result.alarm_name,
                    "region": result.region,
                },
            )
            manual_text = "\n".join(f"• {s[:120]}" for s in result.needs_approval[:5])
            await client.chat_postMessage(
                channel=channel,
                text=f"⚠️ Manual steps required: {result.alert_title}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*⚠️ No runbook matched.* Suggested manual steps:\n{manual_text}",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "✅ Done — Mark Resolved"},
                                "action_id": "acknowledge_action",
                                "value": ack_id,
                                "style": "primary",
                            },
                        ],
                    },
                ],
            )

        # Always index triage result for RAG — unless pending human approval (written on approve)
        _needs_human = bool(
            result.pending_exec_steps
            and settings.pagemenot_approval_gate
            and sev_rank >= _SEV.get(settings.pagemenot_approval_min_severity, 2)
        )
        if not _needs_human:
            from pagemenot.rag import write_and_index_postmortem as _wip

            asyncio.get_event_loop().run_in_executor(
                None, _wip, result, "agent", jira_url if isinstance(jira_url, str) else ""
            )

        # Escalate to on-call channel
        _pd_min_rank = _SEV.get(settings.pagemenot_pd_min_severity, 2)
        if (
            not settings.pagemenot_exec_dry_run
            and not result.resolved_automatically
            and sev_rank >= _pd_min_rank
            and settings.pagemenot_oncall_channel
        ):
            pd_line = f"\n📟 PagerDuty: {pd_url}" if isinstance(pd_url, str) else ""
            jira_line = f"\n🎫 Jira: {jira_url}" if isinstance(jira_url, str) else ""
            await client.chat_postMessage(
                channel=settings.pagemenot_oncall_channel,
                text=(
                    f"{sev} *ESCALATION:* {result.alert_title} ({result.service})\n"
                    f"Confidence: {conf} {result.confidence} — see #{channel}"
                    f"{pd_line}{jira_line}"
                ),
            )

    except Exception as e:
        logger.error(f"Auto-triage failed: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pagemenot.main:app", host="0.0.0.0", port=8080, log_level="info")
