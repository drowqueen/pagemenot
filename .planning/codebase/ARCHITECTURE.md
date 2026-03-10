# Pagemenot Architecture

## System Overview

Pagemenot is an AI SRE copilot: it receives alerts via webhooks or Slack, runs a three-agent CrewAI crew for triage, executes runbook steps autonomously, and escalates to humans when needed.

Two concurrent servers run inside one Docker container:
- **FastAPI** on port 8080 — receives webhooks from external alerting tools
- **Slack Bolt (Socket Mode)** — receives slash commands, mentions, and button interactions

Both converge on a single entry point: `run_triage()` in `pagemenot/triage.py`.

---

## Layers

```
┌─────────────────────────────────────────────────────────┐
│  INBOUND SURFACE                                        │
│  Webhooks (FastAPI)     Slack (Socket Mode)             │
│  /webhooks/pagerduty    /pagemenot triage               │
│  /webhooks/sns          @Pagemenot mention              │
│  /webhooks/generic      channel message monitor         │
│  /webhooks/grafana ...                                  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  TRIAGE LAYER  (pagemenot/triage.py)                    │
│  _parse_alert()   → normalize source → standard fields  │
│  _check_and_register() → dedup TTL gate                 │
│  _seed_mock_if_needed() → mock context for demos        │
│  run_triage()    → orchestrates everything              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  CREW LAYER  (pagemenot/crew.py)                        │
│  build_triage_crew() → 3 sequential CrewAI agents       │
│    monitor     → gather metrics/logs                    │
│    diagnoser   → correlate, root cause                  │
│    remediator  → runbook search, remediation steps      │
└────────────────────────┬────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
┌─────────────────────┐  ┌────────────────────────────────┐
│  TOOLS LAYER        │  │  RAG LAYER (pagemenot/rag.py)  │
│  pagemenot/tools.py │  │  ChromaDB (embedded or remote) │
│  Real integrations  │  │  knowledge/runbooks/   *.md    │
│  Mock fallbacks     │  │  knowledge/postmortems/ *.md   │
└──────────┬──────────┘  └────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│  EXEC LAYER  (tools.py: dispatch_exec_step)             │
│  exec_kubectl()   exec_aws()   exec_shell()             │
│  exec_http()      (GCP via exec_shell wrapping gcloud)  │
│  Approval gate — only <!-- exec: --> tagged steps run   │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│  OUTPUT LAYER  (pagemenot/slack_bot.py + main.py)       │
│  Post triage to Slack thread                            │
│  Approval buttons → _approval_store                     │
│  Jira SM ticket creation / resolution                   │
│  PagerDuty incident creation / resolution               │
│  CW alarm verification polling (_verify_cw_recovery)    │
│  write_and_index_postmortem()                           │
└─────────────────────────────────────────────────────────┘
```

---

## Entry Points

| Source | Entry | Handler |
|--------|-------|---------|
| Webhook (any) | `POST /webhooks/<provider>` | `_auto_triage(source, payload)` in `main.py` |
| Slack slash cmd | `/pagemenot triage <text>` | `handle_command()` → `_do_triage()` in `slack_bot.py` |
| Slack @mention | `app_mention` event | `handle_mention()` → `_do_triage()` in `slack_bot.py` |
| Channel monitor | `message` event on watched channels | `handle_message()` → `_do_triage()` in `slack_bot.py` |
| Approval button | `approve_action` interaction | `handle_approve()` in `slack_bot.py` |
| Reject button | `reject_action` interaction | `handle_reject()` in `slack_bot.py` |
| Acknowledge button | `acknowledge_action` interaction | `handle_acknowledge()` in `slack_bot.py` |
| SNS OK notification | `POST /webhooks/sns` (state=OK) | inline in `sns_webhook()`, closes Jira/PD |
| PD resolve webhook | `POST /webhooks/pagerduty/resolve` | `pagerduty_resolve_webhook()` |
| Jira webhook | `POST /webhooks/jira` | `jira_webhook()` |

---

## Startup Sequence (`lifespan` in `main.py`)

```
1. ingest_all()              — load runbooks + postmortems into ChromaDB
2. create_slack_app()        — wire all Slack event handlers
3. AsyncSocketModeHandler    — connect Slack WebSocket
4. _schedule_verification    — inject CW polling callback into slack_bot (avoids circular import)
5. Resume pending CW verifs  — from /app/data/verifications.json (crash recovery)
6. LLM compliance gate       — block startup if external LLM and no enterprise confirmation
7. _reindex_loop()           — hourly re-ingest of knowledge base
```

---

## Triage Request Lifecycle

```
Alert arrives
     │
     ▼
_parse_alert(source, payload)
  → normalize: title, service, severity, description, alarm_name, region
     │
     ▼
_check_and_register(service, title, severity)
  → TTL dedup (600s critical/high, 1800s medium/low)
  → SUPPRESSED if duplicate within TTL
     │
     ▼
_seed_mock_if_needed(parsed)
  → loads scenario data into mock tools if no real integration configured
     │
     ▼
_redact_sensitive(summary)
  → removes credentials, DSNs, IPs before sending to LLM
     │
     ▼
build_triage_crew(alert_summary).kickoff()   [ThreadPoolExecutor, max 3]
  ┌─ monitor agent  ─ query metrics/logs
  ├─ diagnoser agent ─ root cause, confidence, evidence
  └─ remediator agent ─ steps tagged [AUTO-SAFE] or [NEEDS APPROVAL]
     │
     ▼
_parse_crew_output(raw, parsed_alert)
  → extract root_cause, confidence, remediation_steps, needs_approval → TriageResult
     │
     ▼
_try_runbook_exec(result)
  → get_runbook_exec_steps(query, service)  [ChromaDB cosine search]
  → auto steps: run immediately via dispatch_exec_step()
  → approve steps: queue in result.pending_exec_steps (if APPROVAL_GATE=true)
  → result.resolved_automatically = True if all auto steps succeed
     │
     ▼
Post to Slack / route based on outcome:
  - SUPPRESSED    → quiet suppression note
  - AUTO-RESOLVED → exec log + verified banner + postmortem written
  - PENDING STEPS → approval buttons (or auto-approve timer if confidence=high)
  - NOT RESOLVED  → root cause + analysis + escalate if high/critical
```

---

## Approval Flow

```
result.pending_exec_steps queued
     │
     ├─ confidence=high + exec_enabled → auto-approve timer (PAGEMENOT_AUTOAPPROVE_DELAY)
     │    └─ _autoapprove_timer() waits, then calls dispatch_exec_step() per step
     │
     └─ else → approval buttons posted
          │
          ├─ Approve → handle_approve()
          │    → dispatch_exec_step() per step
          │    → if alarm_name set → _schedule_verification() → _verify_cw_recovery() poll
          │    → else → _resolve_jira_ticket() + _resolve_pagerduty_incident() immediately
          │    → write_and_index_postmortem()
          │
          └─ Reject → handle_reject() → _escalate_unresolved()
               → open Jira + page PD + post to PAGEMENOT_ONCALL_CHANNEL
```

---

## Approval State Store (`_ApprovalStore`)

Three-tier priority, in `pagemenot/slack_bot.py`:

```
Redis (REDIS_URL set, no TTL)
  → /app/data/approvals.json  (file fallback)
    → in-memory dict          (last resort)
```

A separate `_verif_store` instance uses `/app/data/verifications.json` for in-flight CW verifications; these resume on container restart.

---

## Tool Auto-Discovery

`pagemenot/tools.py::get_available_tools()` checks `.env` at startup and returns only tools whose integration is configured. Each tool is a CrewAI `@tool`:

| Agent | Tool | Condition |
|-------|------|-----------|
| monitor | `query_prometheus` | `PROMETHEUS_URL` set |
| monitor | `query_grafana_alerts` | `GRAFANA_URL` set |
| monitor | `search_logs_loki` | `LOKI_URL` set |
| monitor | `query_datadog_metrics` | `DATADOG_API_KEY` set |
| monitor | `query_newrelic_metrics` | `NEWRELIC_API_KEY` set |
| monitor | `get_pagerduty_incident` | `PAGERDUTY_API_KEY` set |
| monitor | `get_opsgenie_alert` | `OPSGENIE_API_KEY` set |
| diagnoser | `get_recent_deploys` | `GITHUB_TOKEN` set |
| diagnoser | `get_pr_diff` | `GITHUB_TOKEN` set |
| diagnoser | `search_past_incidents` | always (ChromaDB) |
| remediator | `search_runbooks` | always (ChromaDB) |
| remediator | `kubectl_rollback` | `KUBECONFIG_PATH` set |
| remediator | `request_human_approval` | always |

If a real tool is not configured, `mock_tools.py` supplies a mock version with the same `@tool` name that returns realistic fake data seeded by scenario data.

---

## Exec Step Dispatch (`dispatch_exec_step`)

Only steps with the HTML comment syntax are dispatched — LLM free text is never executed.

```
<!-- exec: <command> -->          → runs immediately (auto-safe)
<!-- exec:approve: <command> -->  → queued for approval (risky)
```

Routing inside `dispatch_exec_step()`:
- `kubectl *` → `exec_kubectl()`
- `aws *` → CLI arg parsing → `exec_aws()` (boto3)
- `http(s)://` → `exec_http()` (SSRF-guarded)
- anything else → `exec_shell()` (shell=True)

Template substitution before routing: `{{ service }}`, `{{ namespace }}`, `{{ lambda_version }}`.

---

## CW Recovery Verification

After runbook execution for an SNS/CloudWatch-sourced alert:

```
_verify_cw_recovery(alarm_name, region, channel, thread_ts, ...)
  → polls boto3 describe_alarms() every PAGEMENOT_VERIFY_POLL_INTERVAL (default 15s)
  → up to PAGEMENOT_VERIFY_TIMEOUT (default 300s)
  → OK: close Jira, resolve PD, post "Verified healthy", write postmortem
  → TIMEOUT: open Jira + PD if not already open, escalate to oncall channel
```

SNS OK notification also claims the pending verification entry to prevent double-posting.

---

## RAG / Knowledge Base

`pagemenot/rag.py` uses ChromaDB with cosine similarity:

- **Two collections**: `incidents` (postmortems) and `runbooks`
- **Embedded mode** (default): SQLite on `chroma_path` volume
- **Remote mode**: `CHROMA_HOST` + `CHROMA_PORT` for multi-replica
- **Ingest**: on startup + hourly; idempotent upsert by document ID
- **Write**: `write_and_index_postmortem()` called after every resolved incident, creating a `.md` file in `knowledge/postmortems/` and indexing it immediately

---

## LLM Configuration

`pagemenot/crew.py::_build_llm()` supports: `ollama`, `anthropic`, `gemini`, `openai`.

Crew memory (cross-incident via ChromaDB): enabled only when an embedder is available. OpenAI embeddings used for `openai` and `anthropic` providers. Ollama/Gemini: memory disabled.

---

## Severity & Escalation Thresholds

| Threshold | Setting | Default |
|-----------|---------|---------|
| Jira ticket created | `PAGEMENOT_JIRA_MIN_SEVERITY` | `low` |
| PD paged / escalated | `PAGEMENOT_PD_MIN_SEVERITY` | `high` |
| Approval required | `PAGEMENOT_APPROVAL_MIN_SEVERITY` | `high` |

Severity rank: `low=0, medium=1, high=2, critical=3`.

---

## Deduplication

In-memory `_active_incidents` dict in `triage.py`. Key: `(service.lower(), hash(title[:60]))`.

- `critical/high`: 600s TTL
- `medium/low`: 1800s TTL

No cross-instance lock — single-instance safe only. Redis required for multi-replica dedup.
