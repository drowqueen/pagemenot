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
import os
import uuid

from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from pagemenot.config import settings
from pagemenot.triage import run_triage, _executor, _bucket_read, _bucket_write

# Set by main.py at startup — triggers CW alarm polling after approval exec (avoids circular import)
_post_verification_task = None

logger = logging.getLogger("pagemenot.slack")

_app: AsyncApp | None = None
_client: AsyncWebClient | None = None

# Auto-approve timer tasks: task_id → asyncio.Task
_pending_autoapprove: dict[str, asyncio.Task] = {}

# Channel ID → name cache for message event routing (IDs like C1234567 never match names)
_channel_name_cache: dict[str, str] = {}


class _ApprovalStore:
    """Pending approval store — Redis → bucket (GCS/S3) → JSON file → in-memory."""

    _FILE = "/app/data/approvals.json"
    _BUCKET_KEY = "state/approvals.json"

    def __init__(self, file: str | None = None, bucket_key: str | None = None):
        if file:
            self._FILE = file
        if bucket_key:
            self._BUCKET_KEY = bucket_key
        self._mem: dict[str, dict] = {}
        self._redis = None
        self._load_state()

    def _load_state(self):
        bucket = settings.pagemenot_state_bucket
        try:
            if bucket:
                self._mem = _bucket_read(bucket, self._BUCKET_KEY) or {}
                if self._mem:
                    logger.info(
                        "Loaded %d approvals from bucket %s/%s",
                        len(self._mem),
                        bucket,
                        self._BUCKET_KEY,
                    )
            elif os.path.exists(self._FILE):
                with open(self._FILE) as f:
                    self._mem = json.load(f)
                logger.info("Loaded %d pending approvals from %s", len(self._mem), self._FILE)
        except Exception as e:
            logger.warning("Could not load approvals state: %s", e)

    def _save_state(self):
        import os

        bucket = settings.pagemenot_state_bucket
        try:
            if bucket:
                _bucket_write(bucket, self._mem, self._BUCKET_KEY)
            else:
                os.makedirs(os.path.dirname(self._FILE), exist_ok=True)
                with open(self._FILE, "w") as f:
                    json.dump(self._mem, f)
        except Exception as e:
            logger.warning("Could not save approvals state: %s", e)

    async def _client(self):
        if self._redis is None and settings.redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            except ImportError:
                logger.warning("redis package not installed — falling back to file approval store")
        return self._redis

    async def set(self, key: str, value: dict, ttl: int = settings.pagemenot_approval_ttl) -> None:
        r = await self._client()
        if r:
            await r.setex(key, ttl, json.dumps(value))
        else:
            self._mem[key] = value
            self._save_state()

    async def pop(self, key: str) -> dict | None:
        r = await self._client()
        if r:
            async with r.pipeline() as pipe:
                pipe.get(key)
                pipe.delete(key)
                result, _ = await pipe.execute()
            return json.loads(result) if result else None
        value = self._mem.pop(key, None)
        if value is not None:
            self._save_state()
        return value

    async def get_all(self) -> dict[str, dict]:
        """Return snapshot of all entries for startup resume (file-backed, not removed)."""
        return dict(self._mem)


_approval_store = _ApprovalStore(bucket_key="state/approvals.json")
_verif_store = _ApprovalStore(
    file="/app/data/verifications.json", bucket_key="state/verifications.json"
)


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
            await say(
                "Slash command is disabled. Set PAGEMENOT_ENABLE_SLASH_COMMAND=true to enable."
            )
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

        elif sub == "reload":
            await say("🔄 Re-indexing knowledge base…")
            from pagemenot.rag import ingest_all as _ingest

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _ingest)
            await say("✅ Knowledge base re-indexed — new postmortems and runbooks are now active.")

        else:
            await say(
                "*Pagemenot — AI On-Call Copilot*\n\n"
                "• `/pagemenot triage <description>` — Triage an incident\n"
                "• `/pagemenot status` — Show connected integrations\n"
                "• `/pagemenot reload` — Re-index runbooks and postmortems\n"
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
            asyncio.create_task(
                _do_triage(say, source="manual", payload={"text": text}, thread_ts=thread)
            )
        else:
            await say(
                "Let me look into that... (follow-up context coming in v0.2)",
                thread_ts=thread,
            )

    # ── Approval buttons ──────────────────────────────────
    @app.action("approve_action")
    async def handle_approve(ack, body, client):
        await ack()
        from pagemenot.tools import dispatch_exec_step
        from pagemenot.triage import _redact_sensitive

        raw_value = body["actions"][0]["value"]
        # Value format: "approval_id:msg_ts" (msg_ts embedded to always target the right message)
        if ":" in raw_value:
            approval_id, embedded_ts = raw_value.split(":", 1)
        else:
            approval_id, embedded_ts = raw_value, None
        user_id = body["user"]["id"]
        user = body["user"]["name"]
        channel = body["container"].get("channel_id") or body.get("channel", {}).get("id")
        thread = body["container"].get("thread_ts") or body["container"].get("message_ts")
        msg_ts = embedded_ts or body["message"]["ts"]

        entry = await _approval_store.pop(approval_id)
        if not entry:
            logger.warning(
                "Approval %s not found in store (already handled or expired)", approval_id
            )
            # Silently remove the stale buttons — no noisy message
            try:
                await client.chat_update(
                    channel=channel,
                    ts=msg_ts,
                    text="(Approval already handled)",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "_(Approval already handled or expired)_",
                            },
                        }
                    ],
                )
            except Exception:
                pass
            return

        steps = entry["steps"]
        service = entry.get("service", "")

        # Remove buttons immediately — prevents double-click
        await client.chat_update(
            channel=channel,
            ts=msg_ts,
            text=f"✅ Approved by @{user}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ *Approved by <@{user_id}>* — executing {len(steps)} step(s)...",
                    },
                }
            ],
        )

        success = True
        for i, step in enumerate(steps, 1):
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread,
                text=f"⚙️ Step {i}/{len(steps)}: `{step[:120]}`",
            )
            try:
                output = await asyncio.get_running_loop().run_in_executor(
                    _executor, dispatch_exec_step, step, service
                )
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"✅ Step {i}/{len(steps)} done:\n```{_redact_sensitive(output)[:500]}```",
                )
            except Exception as e:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"❌ Step {i}/{len(steps)} failed: `{e}`\nRemaining steps skipped.",
                )
                success = False
                break

        if success:
            alert_title = entry.get("alert_title", "Incident")
            exec_log = [f"Step {i}: `{s}`" for i, s in enumerate(steps, 1)]
            alarm_name = entry.get("alarm_name", "")
            region = entry.get("region", "")
            jira_url = entry.get("jira_url", "")
            pd_url = entry.get("pd_url", "")

            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread,
                text=f"✅ All {len(steps)} step(s) executed successfully.",
            )

            if alarm_name and not settings.pagemenot_exec_dry_run and _post_verification_task:
                # Launch CW polling — "🟢 Resolved" posted when alarm goes OK (or timeout escalates)
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread,
                    text=f"_Monitoring `{alarm_name}` — will confirm healthy when alarm returns to OK..._",
                )
                _post_verification_task(
                    alarm_name, region, channel, thread, jira_url, pd_url, entry, user_id
                )
            else:
                # Non-CW source or dry run — mark resolved immediately
                await client.chat_postMessage(
                    channel=channel,
                    text=f"🟢 *Resolved:* {alert_title}",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"🟢 *Resolved:* {alert_title}\n_Approved by <@{user_id}>, runbook executed successfully._",
                            },
                        }
                    ],
                )
                from pagemenot.main import _resolve_jira_ticket, _resolve_pagerduty_incident

                asyncio.create_task(_resolve_jira_ticket(jira_url))
                asyncio.create_task(_resolve_pagerduty_incident(pd_url, resolved_by=user_id))
                # Write postmortem (best-effort)
                try:
                    from pagemenot.rag import write_and_index_postmortem as _wip
                    from pagemenot.triage import TriageResult as _TR

                    _r = _TR(
                        alert_title=alert_title,
                        service=entry.get("service", ""),
                        severity=entry.get("severity", "unknown"),
                        root_cause=entry.get("root_cause", ""),
                        execution_log=exec_log,
                    )
                    asyncio.get_running_loop().run_in_executor(None, _wip, _r, user_id, jira_url)
                except Exception as _pm_err:
                    logger.warning("Postmortem task setup failed (non-fatal): %s", _pm_err)
        else:
            if not settings.pagemenot_exec_dry_run:
                await _escalate_unresolved(
                    client,
                    channel,
                    entry,
                    reason=f"Runbook execution failed after approval by <@{user_id}>",
                )

    @app.action("reject_action")
    async def handle_reject(ack, body, client):
        await ack()
        raw_value = body["actions"][0]["value"]
        if ":" in raw_value:
            approval_id, embedded_ts = raw_value.split(":", 1)
        else:
            approval_id, embedded_ts = raw_value, None
        user_id = body["user"]["id"]
        user = body["user"]["name"]
        channel = body["container"].get("channel_id") or body.get("channel", {}).get("id")
        msg_ts = embedded_ts or body["message"]["ts"]

        entry = await _approval_store.pop(approval_id)

        await client.chat_update(
            channel=channel,
            ts=msg_ts,
            text=f"❌ Rejected by @{user}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"❌ *Rejected by <@{user_id}>* — steps will not execute.",
                    },
                }
            ],
        )

        if entry and not settings.pagemenot_exec_dry_run:
            await _escalate_unresolved(
                client, channel, entry, reason=f"Runbook rejected by <@{user_id}>"
            )

    @app.action("acknowledge_action")
    async def handle_acknowledge(ack, body, client):
        """Manual resolve — no runbook matched; user confirms they fixed it manually."""
        await ack()
        raw_value = body["actions"][0]["value"]
        approval_id, embedded_ts = (
            raw_value.split(":", 1) if ":" in raw_value else (raw_value, None)
        )
        user_id = body["user"]["id"]
        channel = body["container"].get("channel_id") or body.get("channel", {}).get("id")
        msg_ts = embedded_ts or body["message"]["ts"]

        entry = await _approval_store.pop(approval_id)
        if not entry:
            await client.chat_postEphemeral(
                channel=channel, user=user_id, text="Already acknowledged or expired."
            )
            return

        await client.chat_update(
            channel=channel,
            ts=msg_ts,
            text=f"✅ Acknowledged by <@{user_id}>",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ *Manually resolved by <@{user_id}>* — no runbook matched; steps executed manually.",
                    },
                }
            ],
        )
        await client.chat_postMessage(
            channel=channel,
            text=f"🟢 *Resolved (manual):* {entry.get('alert_title', 'incident')}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🟢 *Resolved:* {entry.get('alert_title', 'incident')}\n"
                        f"_Manually resolved by <@{user_id}>. No runbook matched._",
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "📝 *Action required — two steps:*\n"
                            "1. Add a runbook to `knowledge/runbooks/` so this incident auto-resolves next time\n"
                            "2. Write a postmortem in `knowledge/postmortems/` — "
                            "a draft has been auto-generated and indexed for future reference"
                        ),
                    },
                },
            ],
        )
        from pagemenot.main import _resolve_jira_ticket, _resolve_pagerduty_incident

        asyncio.create_task(_resolve_jira_ticket(entry.get("jira_url", "")))
        asyncio.create_task(
            _resolve_pagerduty_incident(entry.get("pd_url", ""), resolved_by=user_id)
        )
        try:
            from pagemenot.rag import write_and_index_postmortem as _wip
            from pagemenot.triage import TriageResult as _TR

            _r = _TR(
                alert_title=entry.get("alert_title", ""),
                service=entry.get("service", ""),
                severity=entry.get("severity", "unknown"),
                root_cause=entry.get("root_cause", ""),
            )
            asyncio.get_running_loop().run_in_executor(
                None, _wip, _r, user_id, entry.get("jira_url", "")
            )
        except Exception as _e:
            logger.warning("Postmortem task setup failed (non-fatal): %s", _e)

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
    async def handle_message(event, client, say):
        if not settings.pagemenot_enable_channel_monitor:
            return
        if event.get("bot_id") or event.get("subtype"):
            return

        channel_id = event.get("channel", "")
        if not channel_id:
            return

        # watched may contain names OR IDs — resolve channel ID to name for name matching
        watched = {c.strip() for c in settings.pagemenot_alert_channels.split(",")}
        if channel_id not in watched:
            if channel_id not in _channel_name_cache:
                try:
                    info = await client.conversations_info(channel=channel_id)
                    _channel_name_cache[channel_id] = info["channel"]["name"]
                except Exception:
                    _channel_name_cache[channel_id] = channel_id
            if _channel_name_cache[channel_id] not in watched:
                return

        text = event.get("text", "")
        if not text or len(text) < 20:
            return

        if _looks_like_alert(text):
            # Post triage result to pagemenot_channel, not back to the alert source channel
            dest = settings.pagemenot_channel

            async def _say_to_dest(*args, **kwargs):
                kwargs.setdefault("channel", dest)
                return await client.chat_postMessage(*args, **kwargs)

            asyncio.create_task(
                _do_triage(_say_to_dest, source="slack-channel", payload={"text": text})
            )

    return app


async def _escalate_unresolved(client, channel: str, entry: dict, reason: str):
    """Open Jira/PD and ping oncall channel when a human-gated resolution fails or is rejected."""
    from pagemenot.main import _open_jira_ticket, _page_pagerduty
    import types

    result = types.SimpleNamespace(
        severity=entry.get("severity", "high"),
        alert_title=entry.get("alert_title", "Incident"),
        service=entry.get("service", ""),
        root_cause=reason,
        confidence="high",
        duration_seconds=0.0,
    )
    _SEV = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    sev_rank = _SEV.get(result.severity, 0)
    jira_min = _SEV.get(settings.pagemenot_jira_min_severity, 2)
    pd_min = _SEV.get(settings.pagemenot_pd_min_severity, 2)
    tasks = [
        _open_jira_ticket(result) if sev_rank >= jira_min else asyncio.sleep(0),
        _page_pagerduty(result) if sev_rank >= pd_min else asyncio.sleep(0),
    ]
    jira_url, pd_url = await asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(jira_url, str):
        await client.chat_postMessage(channel=channel, text=f"🎫 Jira ticket opened: {jira_url}")
    if isinstance(pd_url, str):
        await client.chat_postMessage(
            channel=channel, text=f"📟 On-call paged via PagerDuty: {pd_url}"
        )
    if settings.pagemenot_oncall_channel and sev_rank >= pd_min:
        sev_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(result.severity, "⚪")
        pd_line = f"\n📟 PagerDuty: {pd_url}" if isinstance(pd_url, str) else ""
        jira_line = f"\n🎫 Jira: {jira_url}" if isinstance(jira_url, str) else ""
        similar_incidents = entry.get("similar_incidents", [])
        similar_line = (
            "\n\n💡 *Similar past incidents:*\n"
            + "\n".join(f"• {s[:120]}" for s in similar_incidents[:3])
            if similar_incidents
            else ""
        )
        await client.chat_postMessage(
            channel=settings.pagemenot_oncall_channel,
            text=f"{sev_emoji} *ESCALATION:* {result.alert_title} ({result.service})\n_{reason}_{pd_line}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{sev_emoji} *ESCALATION — human action required*\n"
                            f"*Incident:* {result.alert_title}\n"
                            f"*Service:* {result.service}\n"
                            f"*Reason:* _{reason}_"
                            f"{pd_line}{jira_line}{similar_line}"
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "📝 *After resolving, write a postmortem:*\n"
                            "• Document root cause and fix in `knowledge/postmortems/`\n"
                            "• If no runbook exists, add one to `knowledge/runbooks/` — "
                            "pagemenot will use it to auto-resolve next time"
                        ),
                    },
                },
            ],
        )


async def _do_triage(say, source: str, payload: dict, thread_ts: str | None = None):
    """Run triage and post results. This is the bridge between Slack and CrewAI."""

    working_msg = await say(
        "🔍 *Triage crew activated.* Gathering data, analyzing, and preparing recommendations...",
        thread_ts=thread_ts,
    )
    thread = working_msg.get("ts") if not thread_ts else thread_ts

    try:
        result = await run_triage(source=source, payload=payload)

        sev = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
            result.severity, "⚪"
        )
        conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result.confidence, "⚪")

        # Suppressed (duplicate or low-severity)
        if result.suppressed:
            label = "Low-severity" if result.severity == "low" else "Duplicate"
            await say(f"⚪ {label} suppressed: {result.alert_title}", thread_ts=thread)
            return

        # Auto-resolved — post analysis + exec log + resolved banner
        if result.resolved_automatically:
            dry = settings.pagemenot_exec_dry_run
            label = "Would auto-resolve" if dry else "Auto-resolved"
            # Analysis
            clean_output = (
                result.raw_output.replace("```sh\n", "")
                .replace("```bash\n", "")
                .replace("```\n", "")
                .replace("```", "")
            )
            for i, chunk in enumerate(
                _chunk_text(clean_output, settings.pagemenot_slack_chunk_size)[
                    : settings.pagemenot_slack_max_chunks
                ]
            ):
                await say(
                    text=f"Analysis (part {i + 1})",
                    blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}],
                    thread_ts=thread,
                )
            # Exec log
            if result.execution_log:
                exec_text = "\n\n".join(result.execution_log[:10])
                await say(
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
                    thread_ts=thread,
                )
            icon = "🟢" if not dry else "🔵"
            resolve_label = "Resolved" if not dry else "Dry-run resolved"
            resolve_detail = (
                "Runbook executed successfully"
                if not dry
                else "Dry-run complete — no real commands were run"
            )
            # Thread resolved message
            await say(
                text=f"{icon} {resolve_label}: {result.alert_title}",
                blocks=[
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{icon} {resolve_label}: {result.alert_title[:80]}",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{resolve_detail}. Triage took {result.duration_seconds:.0f}s.",
                        },
                    },
                ],
                thread_ts=thread,
            )
            # Channel-level resolved post (not in thread)
            channel = working_msg.get("channel", settings.pagemenot_channel)
            await _client.chat_postMessage(
                channel=channel,
                text=f"{icon} *{resolve_label}:* {result.alert_title}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{icon} *{resolve_label}:* {result.alert_title}\n"
                            f"_{resolve_detail} in {result.duration_seconds:.0f}s_",
                        },
                    },
                ],
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

        # Strip markdown code fences from LLM output — Slack renders mrkdwn directly
        clean_output = (
            result.raw_output.replace("```sh\n", "")
            .replace("```bash\n", "")
            .replace("```\n", "")
            .replace("```", "")
        )
        for i, chunk in enumerate(
            _chunk_text(clean_output, settings.pagemenot_slack_chunk_size)[
                : settings.pagemenot_slack_max_chunks
            ]
        ):
            await say(
                text=f"Detailed analysis (part {i + 1})",
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}],
                thread_ts=thread,
            )

        # Post runbook execution log (commands + outputs) to thread
        if result.execution_log:
            exec_text = "\n\n".join(result.execution_log[:10])
            await say(
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
                thread_ts=thread,
            )

        # Approval gate: pending runbook exec steps require human sign-off.
        # High confidence + exec enabled → auto-approve after delay (cancellable).
        # Otherwise → show approve/reject buttons.
        if result.pending_exec_steps:
            channel = working_msg.get("channel", settings.pagemenot_channel)

            # Create Jira/PD before storing approval entry so URLs are available on resolve
            from pagemenot.main import _open_jira_ticket, _page_pagerduty

            _SEV = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            sev_rank = _SEV.get(result.severity, 0)
            _jira_url = _pd_url = None
            if not settings.pagemenot_exec_dry_run:
                jira_min = _SEV.get(settings.pagemenot_jira_min_severity, 2)
                pd_min = _SEV.get(settings.pagemenot_pd_min_severity, 2)
                _jira_url, _pd_url = await asyncio.gather(
                    _open_jira_ticket(result) if sev_rank >= jira_min else asyncio.sleep(0),
                    _page_pagerduty(result) if sev_rank >= pd_min else asyncio.sleep(0),
                    return_exceptions=True,
                )
                if not isinstance(_jira_url, str):
                    _jira_url = None
                if not isinstance(_pd_url, str):
                    _pd_url = None
                if _jira_url:
                    await say(text=f"🎫 Jira ticket opened: {_jira_url}", thread_ts=thread)
                if _pd_url:
                    await say(text=f"📟 On-call paged via PagerDuty: {_pd_url}", thread_ts=thread)

            if result.confidence == "high" and settings.pagemenot_exec_enabled:
                task_id = str(uuid.uuid4())[:8]
                delay_min = settings.pagemenot_autoapprove_delay // 60
                steps_text = "\n".join(f"• `{s[:100]}`" for s in result.pending_exec_steps[:5])
                await say(
                    text="Runbook steps pending auto-approval",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"⚙️ *Runbook steps will auto-execute in {delay_min} min* (cancel to block):\n"
                                    f"{steps_text}"
                                ),
                            },
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                                    "action_id": "cancel_autoapprove",
                                    "value": task_id,
                                    "style": "danger",
                                }
                            ],
                        },
                    ],
                    thread_ts=thread,
                )
                task = asyncio.create_task(
                    _autoapprove_timer(
                        channel, thread, result.pending_exec_steps, result.service, task_id
                    )
                )
                _pending_autoapprove[task_id] = task
            else:
                approval_id = str(uuid.uuid4())[:8]
                await _approval_store.set(
                    approval_id,
                    {
                        "steps": result.pending_exec_steps,
                        "service": result.service or "",
                        "alert_title": result.alert_title or "",
                        "severity": result.severity or "high",
                        "root_cause": result.root_cause or "",
                        "alarm_name": result.alarm_name or "",
                        "region": result.region or "",
                        "similar_incidents": result.similar_incidents or [],
                        "jira_url": _jira_url or "",
                        "pd_url": _pd_url or "",
                    },
                )
                steps_text = "\n".join(f"• `{s[:100]}`" for s in result.pending_exec_steps[:5])
                await _client.chat_postMessage(
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

    not_connected_str = (
        "\n".join(f"  💡 {n}" for n in not_connected) if not_connected else "  (all connected!)"
    )

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
        "alert",
        "alerting",
        "firing",
        "triggered",
        "pagerduty",
        "opsgenie",
        "incident",
        "outage",
        "degraded",
        "down",
        "error rate",
        "p99",
        "latency",
        "oomkill",
        "crashloop",
        "5xx",
        "500",
        "timeout",
        "cpu",
        "memory",
        "disk full",
        "high",
        "critical",
        "warning",
        "sev1",
        "sev2",
        "p1",
        "p2",
        "🔴",
        "🟠",
        "⚠️",
        "🚨",
    ]
    return any(kw in lower for kw in alert_keywords)


def get_client() -> AsyncWebClient:
    if _client is None:
        raise RuntimeError("Slack not initialized")
    return _client
