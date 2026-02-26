"""
Slack bot — the only interface teams interact with.

They never see CrewAI, agents, tools, or configs beyond .env.
They see:
  /pagemenot triage "something is broken"
  → Pagemenot works → Result in thread
"""

import asyncio
import json
import logging
import uuid

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from pagemenot.config import settings
from pagemenot.triage import run_triage, _executor

logger = logging.getLogger("pagemenot.slack")

_app: AsyncApp | None = None
_client: AsyncWebClient | None = None

# Auto-approve timer tasks: task_id → asyncio.Task
_pending_autoapprove: dict[str, asyncio.Task] = {}


def create_slack_app() -> AsyncApp:
    """Create and wire up the Slack app. Called once at startup."""
    global _app, _client

    app = AsyncApp(token=settings.slack_bot_token)
    _app = app
    _client = app.client

    # ── Slash command ─────────────────────────────────────
    @app.command("/pagemenot")
    async def handle_command(ack, command, say):
        await ack()
        if not settings.pagemenot_enable_slash_command:
            await say("Slash command is disabled. Set PAGEMENOT_ENABLE_SLASH_COMMAND=true to enable.")
            return

        text = command.get("text", "").strip()
        parts = text.split(maxsplit=1)
        sub = parts[0].lower() if parts else "help"
        args = parts[1] if len(parts) > 1 else ""

        if sub == "triage":
            if not args:
                await say(
                    "Usage: `/pagemenot triage <describe the issue>`\n"
                    "Example: `/pagemenot triage payment-service returning 500s since 2 minutes ago`"
                )
                return
            await _do_triage(say, source="manual", payload={"text": args})

        elif sub == "status":
            await _show_status(say)

        else:
            await say(
                "*Pagemenot — AI On-Call Copilot*\n\n"
                "• `/pagemenot triage <description>` — Triage an incident\n"
                "• `/pagemenot status` — Show connected integrations\n"
                "• Mention `@Pagemenot` to triage from any channel\n"
                "• Post alerts in watched channels for auto-triage"
            )

    # ── @mention handler ──────────────────────────────────
    @app.event("app_mention")
    async def handle_mention(event, say):
        if not settings.pagemenot_enable_mentions:
            return
        text = event.get("text", "")
        thread = event.get("thread_ts") or event.get("ts")

        if not event.get("thread_ts"):
            # Fire-and-forget — triage can take minutes; don't block the event handler
            asyncio.create_task(_do_triage(say, source="manual", payload={"text": text}, thread_ts=thread))
        else:
            await say(
                "Let me look into that... (follow-up context coming in v0.2)",
                thread_ts=thread,
            )

    # ── Approval buttons ──────────────────────────────────
    @app.action("approve_action")
    async def handle_approve(ack, body, say):
        await ack()
        user = body["user"]["name"]
        action_id = body["actions"][0]["value"]
        thread = body["container"].get("thread_ts") or body["container"].get("message_ts")

        await say(
            f"✅ Action approved by @{user}. Executing...\n"
            f"(Automated execution coming in v0.4 — for now, run the suggested command manually)",
            thread_ts=thread,
        )

    @app.action("reject_action")
    async def handle_reject(ack, body, say):
        await ack()
        user = body["user"]["name"]
        thread = body["container"].get("thread_ts") or body["container"].get("message_ts")
        await say(f"❌ Action rejected by @{user}.", thread_ts=thread)

    @app.action("feedback_positive")
    async def handle_thumbs_up(ack, body):
        await ack()
        logger.info(f"Positive feedback from {body['user']['name']}")

    @app.action("feedback_negative")
    async def handle_thumbs_down(ack, body):
        await ack()
        logger.info(f"Negative feedback from {body['user']['name']}")

    @app.action("cancel_autoapprove")
    async def handle_cancel_autoapprove(ack, body, say):
        await ack()
        task_id = body["actions"][0]["value"]
        task = _pending_autoapprove.pop(task_id, None)
        if task:
            task.cancel()
            user = body["user"]["name"]
            thread = body["container"].get("thread_ts") or body["container"].get("message_ts")
            await say(f"❌ Auto-execution cancelled by @{user}.", thread_ts=thread)

    @app.event("message")
    async def handle_message(event, say):
        if not settings.pagemenot_enable_channel_monitor:
            return
        if event.get("bot_id") or event.get("subtype"):
            return

        channel = event.get("channel", "")
        channel_name = event.get("channel_name", "")
        watched = [c.strip() for c in settings.pagemenot_alert_channels.split(",")]
        if channel not in watched and channel_name not in watched:
            return

        text = event.get("text", "")
        if not text or len(text) < 20:
            return

        if _looks_like_alert(text):
            # Fire-and-forget — triage blocks; Slack retries if handler takes >3s
            asyncio.create_task(_do_triage(say, source="slack-channel", payload={"text": text}))

    return app


async def _do_triage(say, source: str, payload: dict, thread_ts: str | None = None):
    """Run triage and post results. This is the bridge between Slack and CrewAI."""

    working_msg = await say(
        "🔍 *Triage crew activated.* Gathering data, analyzing, and preparing recommendations...",
        thread_ts=thread_ts,
    )
    thread = working_msg.get("ts") if not thread_ts else thread_ts

    try:
        result = await run_triage(source=source, payload=payload)

        sev = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(result.severity, "⚪")
        conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")

        # Suppressed (duplicate or low-severity)
        if result.suppressed:
            label = "Low-severity" if result.severity == "low" else "Duplicate"
            await say(f"⚪ {label} suppressed: {result.alert_title}", thread_ts=thread)
            return

        # Auto-resolved
        if result.resolved_automatically:
            log_text = "\n".join(result.execution_log) if result.execution_log else ""
            await say(
                text=(
                    f"✅ *Auto-resolved:* {result.alert_title}\n"
                    f"⏱️ {result.duration_seconds:.1f}s\n\n"
                    + (f"*Steps executed:*\n{log_text}" if log_text else "")
                ),
                thread_ts=thread,
            )
            return

        # Post triage result
        header_text = f"{sev} {result.alert_title}"[:150]
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": header_text}},
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*🔍 Root Cause* (confidence: {conf} {result.confidence})\n\n"
                        f"{result.root_cause}"
                    ),
                },
            },
        ]
        await say(text=f"{sev} {result.alert_title}", blocks=blocks, thread_ts=thread)

        for i, chunk in enumerate(_chunk_text(result.raw_output, 2900)[:3]):
            await say(
                text=f"Detailed analysis (part {i + 1})",
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"```{chunk}```"}}],
                thread_ts=thread,
            )

        # Auto-approve timer for [AUTO-SAFE] steps (exec enabled + high confidence)
        autosafe = [s for s in result.remediation_steps if "[AUTO-SAFE]" in s]
        if (autosafe and result.confidence == "high" and settings.pagemenot_exec_enabled):
            task_id = str(uuid.uuid4())[:8]
            delay_min = settings.pagemenot_autoapprove_delay // 60
            steps_text = "\n".join(f"• {s[:120]}" for s in autosafe[:5])
            await say(
                text="Auto-safe steps pending",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"⚙️ *Auto-safe steps* (will execute in {delay_min} min unless cancelled):\n"
                                f"{steps_text}"
                            ),
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [{
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Cancel"},
                            "action_id": "cancel_autoapprove",
                            "value": task_id,
                            "style": "danger",
                        }],
                    },
                ],
                thread_ts=thread,
            )
            channel = working_msg.get("channel", settings.pagemenot_channel)
            task = asyncio.create_task(
                _autoapprove_timer(channel, thread, autosafe, result.service, task_id)
            )
            _pending_autoapprove[task_id] = task

        # Approval buttons for [NEEDS APPROVAL] steps
        elif result.needs_approval:
            approval_text = "\n".join(f"• {a}" for a in result.needs_approval)
            await say(
                text="Actions requiring approval",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*⚠️ Actions requiring approval:*\n{approval_text}"},
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "✅ Approve"},
                                "action_id": "approve_action",
                                "value": "triage_action",
                                "style": "primary",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "❌ Reject"},
                                "action_id": "reject_action",
                                "value": "triage_action",
                                "style": "danger",
                            },
                        ],
                    },
                ],
                thread_ts=thread,
            )

        # Feedback buttons
        await say(
            text="Was this helpful?",
            blocks=[
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👍 Helpful"},
                            "action_id": "feedback_positive",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👎 Wrong"},
                            "action_id": "feedback_negative",
                            "style": "danger",
                        },
                    ],
                },
            ],
            thread_ts=thread,
        )

        await say(f"⏱️ Triage completed in {result.duration_seconds:.1f}s", thread_ts=thread)

    except Exception as e:
        logger.error(f"Triage failed: {e}", exc_info=True)
        await say(f"❌ Triage failed: {str(e)[:200]}. Check logs for details.", thread_ts=thread)


async def _autoapprove_timer(
    channel: str,
    thread_ts: str,
    steps: list[str],
    service: str,
    task_id: str,
):
    """Wait for autoapprove delay, then execute AUTO-SAFE steps."""
    from pagemenot.tools import dispatch_exec_step

    try:
        await asyncio.sleep(settings.pagemenot_autoapprove_delay)
    except asyncio.CancelledError:
        return
    finally:
        _pending_autoapprove.pop(task_id, None)

    from pagemenot.triage import _redact_sensitive

    client = get_client()
    results = []
    for step in steps:
        try:
            output = await asyncio.get_running_loop().run_in_executor(
                _executor, dispatch_exec_step, step, service
            )
            results.append(f"✅ {step[:80]}: {_redact_sensitive(output)[:100]}")
        except Exception as e:
            results.append(f"❌ {step[:80]}: {e}")

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"⚙️ Auto-executed {len(results)} step(s):\n" + "\n".join(results),
    )


async def _show_status(say):
    """Show what's connected — helps teams see what they can add."""
    connected = settings.enabled_integrations
    if connected:
        connected_str = "\n".join(f"  ✅ {i}" for i in connected)
    else:
        connected_str = "  (none yet)"

    not_connected = []
    if not settings.prometheus_url:
        not_connected.append("Prometheus (PROMETHEUS_URL)")
    if not settings.github_token:
        not_connected.append("GitHub (GITHUB_TOKEN)")
    if not settings.loki_url:
        not_connected.append("Loki (LOKI_URL)")
    if not settings.grafana_url:
        not_connected.append("Grafana (GRAFANA_URL, GRAFANA_API_KEY)")
    if not settings.pagerduty_api_key:
        not_connected.append("PagerDuty (PAGERDUTY_API_KEY)")
    if not settings.kubeconfig_path:
        not_connected.append("Kubernetes (KUBECONFIG_PATH)")

    not_connected_str = "\n".join(f"  💡 {n}" for n in not_connected) if not_connected else "  (all connected!)"

    await say(
        f"*🦞 Pagemenot Status*\n\n"
        f"*Connected:*\n{connected_str}\n\n"
        f"*Available to add:*\n{not_connected_str}\n\n"
        f"_Add integrations by setting env vars in `.env` and restarting._"
    )


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks for Slack's character limits."""
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good break point
        break_at = text.rfind("\n", 0, max_len)
        if break_at < max_len // 2:
            break_at = max_len
        chunks.append(text[:break_at])
        text = text[break_at:].lstrip("\n")
    return chunks


def _looks_like_alert(text: str) -> bool:
    """Heuristic: does this Slack message look like an alert that needs triage?"""
    lower = text.lower()
    alert_keywords = [
        "alert", "alerting", "firing", "triggered", "pagerduty", "opsgenie",
        "incident", "outage", "degraded", "down", "error rate", "p99",
        "latency", "oomkill", "crashloop", "5xx", "500", "timeout",
        "cpu", "memory", "disk full", "high", "critical", "warning",
        "sev1", "sev2", "p1", "p2", "🔴", "🟠", "⚠️", "🚨",
    ]
    return any(kw in lower for kw in alert_keywords)


def get_client() -> AsyncWebClient:
    if _client is None:
        raise RuntimeError("Slack not initialized")
    return _client
