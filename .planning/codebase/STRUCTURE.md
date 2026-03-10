# Pagemenot Directory Structure

## Top-Level Layout

```
pagemenot/
├── pagemenot/              # Core Python package
├── knowledge/              # Operator-managed knowledge base (markdown)
│   ├── runbooks/           # Operational procedures with <!-- exec: --> tags
│   └── postmortems/        # Incident post-mortems (hand-written + auto-generated)
├── scripts/
│   └── simulate_incident.py   # Test scenario runner
├── docs/
│   └── deployment.md
├── .planning/              # Planning documents (not shipped)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env                    # Not committed — all runtime config
└── TODO.md
```

---

## Core Package: `pagemenot/`

| File | Role |
|------|------|
| `pagemenot/main.py` | FastAPI app, lifespan, all webhook endpoints, Jira/PD helpers, CW verification |
| `pagemenot/triage.py` | `run_triage()` orchestrator, `TriageResult` dataclass, alert parsing, dedup |
| `pagemenot/crew.py` | `build_triage_crew()` — CrewAI agents + tasks + LLM config |
| `pagemenot/tools.py` | Tool registry, real integrations, exec functions (`dispatch_exec_step`, `exec_aws`, `exec_kubectl`, `exec_shell`, `exec_http`), `get_runbook_exec_steps` |
| `pagemenot/mock_tools.py` | Mock versions of every tool, seeded by scenario data |
| `pagemenot/slack_bot.py` | Slack Bolt app, all event/action handlers, `_ApprovalStore`, `_do_triage()` |
| `pagemenot/rag.py` | ChromaDB ingestion, `write_and_index_postmortem()`, `search_past_incidents` backing |
| `pagemenot/config.py` | `Settings` (Pydantic BaseSettings) — single source of truth for all config |
| `pagemenot/__init__.py` | Empty |

No `knowledge/` subdirectory inside the package — the package imports from the repo-root `knowledge/` directory.

Note: `pagemenot/rag.py` is the RAG module (not `pagemenot/knowledge/rag.py`). The `pagemenot/knowledge/` directory referenced in CLAUDE.md does not exist in this codebase.

---

## `pagemenot/main.py` — Key Sections

| Lines (approx) | Content |
|-----------------|---------|
| 1–37 | Imports, logging, rate limiter setup |
| 39–63 | HMAC signature verification helpers |
| 65–194 | `lifespan()` — startup/shutdown sequence |
| 197–200 | FastAPI app instantiation |
| 202–208 | `GET /health` |
| 216–445 | Webhook endpoints (pagerduty, grafana, alertmanager, generic, sns, opsgenie, datadog, newrelic) |
| 448–515 | Resolve webhooks (pagerduty/resolve, jira) |
| 517–599 | `_page_pagerduty()` |
| 602–683 | `_open_jira_ticket()` |
| 686–785 | `_resolve_jira_ticket()`, `_resolve_pagerduty_incident()` |
| 788–900 | `_alarm_incidents` dict, `_verify_cw_recovery()` |
| 902–end | `_auto_triage()` — webhook result routing to Slack |

---

## `pagemenot/tools.py` — Key Sections

| Lines (approx) | Content |
|-----------------|---------|
| 1–140 | `get_available_tools()` registry + `_safe_name()` |
| 142–680 | `@tool` functions: prometheus, grafana, loki, pagerduty, opsgenie, datadog, newrelic, github deploys, github PR diff, `search_past_incidents`, `search_runbooks`, `request_human_approval`, `kubectl_rollback` |
| 714–870 | Exec functions: `exec_kubectl()`, `exec_aws()`, `exec_shell()`, `exec_http()` |
| 927–1003 | Helpers: `_resolve_lambda_version()`, `_self_instance_id()`, `_parse_shorthand()`, `_safe_service_name()` |
| 1005–1182 | `dispatch_exec_step()` — parse + route a single runbook exec tag |
| 1185–end | `get_runbook_exec_steps()` — ChromaDB search → split auto/approve steps |

---

## `pagemenot/config.py` — Settings Reference

All settings loaded from `.env` via Pydantic BaseSettings. Key groups:

| Group | Key Variables |
|-------|--------------|
| Required | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| LLM | `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_URL` |
| Vector store | `CHROMA_PATH`, `CHROMA_HOST`, `CHROMA_PORT` |
| Slack behavior | `PAGEMENOT_CHANNEL`, `PAGEMENOT_ALERT_CHANNELS`, `PAGEMENOT_ONCALL_CHANNEL` |
| Integrations | `PROMETHEUS_URL`, `GRAFANA_URL`, `LOKI_URL`, `DATADOG_API_KEY`, `NEWRELIC_API_KEY`, `PAGERDUTY_API_KEY`, `OPSGENIE_API_KEY`, `GITHUB_TOKEN`, `KUBECONFIG_PATH` |
| Execution | `PAGEMENOT_EXEC_ENABLED`, `PAGEMENOT_EXEC_DRY_RUN`, `PAGEMENOT_APPROVAL_GATE`, `PAGEMENOT_AUTOAPPROVE_DELAY` |
| Severity gates | `PAGEMENOT_JIRA_MIN_SEVERITY`, `PAGEMENOT_PD_MIN_SEVERITY`, `PAGEMENOT_APPROVAL_MIN_SEVERITY` |
| Dedup | `PAGEMENOT_DEDUP_TTL_SHORT`, `PAGEMENOT_DEDUP_TTL_LONG` |
| CW verification | `PAGEMENOT_VERIFY_TIMEOUT`, `PAGEMENOT_VERIFY_POLL_INTERVAL` |
| AWS | `AWS_REGION`, `AWS_ROLE_ARN` |
| Webhook secrets | `WEBHOOK_SECRET_PAGERDUTY`, `WEBHOOK_SECRET_GRAFANA`, etc. |
| State store | `REDIS_URL` |

---

## Knowledge Base: `knowledge/`

### `knowledge/runbooks/` (18 files)

Runbooks are markdown files. Steps with `<!-- exec: -->` or `<!-- exec:approve: -->` HTML comment tags are extracted and executed autonomously.

```
cloud-run-unavailable.md
database-connection-pool.md
disk-pressure.md
ec2-high-cpu.md
ec2-nginx-restart.md
ecs-service-unhealthy.md
gce-instance-stopped.md
gce-nginx-stopped.md
high-cpu-throttling.md
high-error-rate.md
high-latency.md
lambda-error-rate.md
oomkill-response.md
pod-crashloop.md
rds-high-connections.md
rds-instance-stopped.md
rollback-procedure.md
ssl-certificate-expiry.md
```

### `knowledge/postmortems/` (mixed: hand-written + auto-generated)

Hand-written canonical incidents:
```
inc-189-payment-500s.md
inc-201-checkout-oomkill.md
inc-215-223-gateway-db.md
api-gateway_20260304-111809.md
nginx-cache_20260304-165934.md
nginx-cache_20260304-170236-ab739d.md
```

Auto-generated (by `write_and_index_postmortem()` — naming: `<service>_<YYYYMMDD-HHMMSS>-<uuid6>.md`):
```
checkout-service_20260302-*.md
payment-service_20260302-*.md
user-service_20260302-*.md
... (many more)
```

---

## Scripts

| File | Purpose |
|------|---------|
| `scripts/simulate_incident.py` | Defines `SCENARIOS` dict; sends webhook + seeds mock context for local testing |

Scenarios: `checkout-oom` (kubectl exec path), `payment-500s` (approval path + PD + Jira).

---

## Docker / Deployment

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build; app user `appuser`; exposes port 8080 |
| `docker-compose.yml` | Service: `pagemenot`; volumes: `chromadata` (ChromaDB), `appdata` (approvals/verifications JSON) |

Runtime volume mounts:
- `chromadata:/app/data/chroma` — ChromaDB SQLite
- `appdata:/app/data` — `approvals.json`, `verifications.json`

---

## Naming Conventions

| Convention | Example |
|------------|---------|
| Runbooks | `<symptom-or-service>.md` lowercase hyphenated |
| Auto-generated postmortems | `<service>_<YYYYMMDD-HHMMSS>-<uuid6>.md` |
| Hand-written postmortems | `inc-<N>-<description>.md` or `<service>_<date>.md` |
| Settings env vars | `PAGEMENOT_*` prefix for app-specific settings |
| Webhook secrets | `WEBHOOK_SECRET_<PROVIDER>` |
| Internal functions | `_` prefix for module-private helpers |
| CrewAI tools | `@tool("Human Readable Name")` decorator on plain functions |

---

## Data Persistence

| Data | Storage | Path |
|------|---------|------|
| Knowledge embeddings | ChromaDB SQLite | `/app/data/chroma/` |
| Pending approvals | Redis → JSON file → in-memory | `/app/data/approvals.json` |
| In-flight CW verifications | JSON file | `/app/data/verifications.json` |
| Auto-generated postmortems | Markdown files | `knowledge/postmortems/` |
| Config | Environment / `.env` | `.env` (never committed) |

---

## What Lives Where (Quick Reference)

| Question | Answer |
|----------|--------|
| Where do webhook routes live? | `pagemenot/main.py` — `@app.post("/webhooks/*")` |
| Where does triage orchestration live? | `pagemenot/triage.py::run_triage()` |
| Where are CrewAI agents defined? | `pagemenot/crew.py::build_triage_crew()` |
| Where is tool auto-discovery? | `pagemenot/tools.py::get_available_tools()` |
| Where do runbook steps execute? | `pagemenot/tools.py::dispatch_exec_step()` |
| Where is approval state stored? | `pagemenot/slack_bot.py::_ApprovalStore` |
| Where are Slack buttons wired? | `pagemenot/slack_bot.py` (`@app.action("approve_action")` etc.) |
| Where does RAG indexing happen? | `pagemenot/rag.py::ingest_all()` + `write_and_index_postmortem()` |
| Where is all config? | `pagemenot/config.py::Settings` |
| Where do runbooks live? | `knowledge/runbooks/*.md` |
| Where do postmortems live? | `knowledge/postmortems/*.md` |
