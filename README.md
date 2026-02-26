# Pagemenot — AI On-Call Copilot

Self-hosted AI SRE. Alert fires → 3-agent crew triages → root cause + remediation plan posted to Slack with human approval gate.

---

## Workflow

```
 ALERT SOURCES                    PAGEMENOT                        OUTPUT
 ─────────────                    ─────────                        ──────

 PagerDuty ─────────────────┐
 OpsGenie  ─────────────────┤
 Grafana   ─────────────────┼──▶  /webhooks/*  ──▶  parse  ──┐
 Datadog   ─────────────────┤     /pagemenot triage           │
 New Relic ─────────────────┤                                 │
 Alertmanager ──────────────┘                                 │
 Slack mention / slash cmd ────────────────────────────────────┘
                                                               │
                                                               ▼
                                                    ┌──────────────────┐
                                                    │  CrewAI Crew     │
                                                    │                  │
                                        ┌───────────┤  Supervisor      ├────────────┐
                                        │           └──────────────────┘            │
                                        ▼                    ▼                      ▼
                               ┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
                               │ MonitorAgent │    │ DiagnoserAgent   │    │ RemediatorAgent  │
                               └──────┬──────┘    └────────┬─────────┘    └────────┬─────────┘
                                      │                    │                       │
                               Prometheus/AMP        GitHub deploys          Runbook RAG
                               Grafana/Cloud          PR diffs                kubectl rollback
                               Loki/Cloud             Past incidents          ⚠ Human gate
                               Datadog                (ChromaDB RAG)
                               New Relic
                               PagerDuty / OpsGenie
                                      │                    │                       │
                                      └────────────────────┴───────────────────────┘
                                                           │
                                                           ▼
                                              ┌────────────────────────┐
                                              │  Slack thread          │
                                              │  • Root cause          │
                                              │  • Confidence level    │
                                              │  • Remediation steps   │
                                              │  • [Approve] [Reject]  │
                                              └────────────────────────┘
```

No integrations configured → mock layer activates automatically. The crew still runs.

---

## Setup

```bash
cp .env.example .env   # edit this one file — all config lives here
docker compose up -d
```

**Slack app** (one-time):
1. https://api.slack.com/apps → **Create New App → From scratch**
2. **OAuth & Permissions → Bot Token Scopes**: `app_mentions:read`, `channels:history`, `channels:read`, `chat:write`, `commands`, `groups:history`
3. **Event Subscriptions → Subscribe to bot events**: `app_mention`, `message.channels`
4. **Slash Commands**: create `/pagemenot`
5. **Socket Mode**: enable, generate app-level token with `connections:write` scope
6. **Install to workspace** → copy **Bot Token** (`xoxb-…`) → `SLACK_BOT_TOKEN`, app token (`xapp-…`) → `SLACK_APP_TOKEN`

**LLM** — pick one, set in `.env`:

| Provider | `LLM_PROVIDER` | Key var |
|----------|---------------|---------|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini` | `GEMINI_API_KEY` |
| Ollama | `ollama` | `OLLAMA_URL` |

All other integrations (Prometheus, Loki, Grafana, PagerDuty, etc.) are optional — set their vars in `.env` to activate. Unset = mock fallback.

**Test without real monitoring:**

```bash
python scripts/simulate_incident.py payment-500s
# --source opsgenie | datadog | newrelic | alertmanager
```

Scenarios: `payment-500s`, `checkout-oom`, `db-connection-pool`, `cert-renewal`, `traffic-spike`, `--random`

---

## Integrations

Set env vars in `.env` — each one upgrades that tool from mock → live data.

| Category | Tool | Required vars |
|----------|------|---------------|
| Metrics | Prometheus (self-hosted) | `PROMETHEUS_URL` |
| Metrics | AWS Managed Prometheus | `PROMETHEUS_URL` + `PROMETHEUS_AUTH_TOKEN` |
| Metrics | GCP Managed Prometheus | `PROMETHEUS_URL` + `PROMETHEUS_AUTH_TOKEN` |
| Metrics | Grafana Cloud (Prometheus) | `PROMETHEUS_URL` + `PROMETHEUS_AUTH_TOKEN` |
| Metrics | Datadog | `DATADOG_API_KEY` + `DATADOG_APP_KEY` |
| Metrics | New Relic | `NEWRELIC_API_KEY` + `NEWRELIC_ACCOUNT_ID` |
| Dashboards | Grafana (self-hosted) | `GRAFANA_URL` + `GRAFANA_API_KEY` |
| Dashboards | Grafana Cloud | `GRAFANA_URL` + `GRAFANA_API_KEY` + `GRAFANA_ORG_ID` |
| Logs | Loki (self-hosted) | `LOKI_URL` |
| Logs | Loki (Grafana Cloud) | `LOKI_URL` + `LOKI_AUTH_TOKEN` + `LOKI_ORG_ID` |
| On-call | PagerDuty | `PAGERDUTY_API_KEY` |
| On-call | OpsGenie | `OPSGENIE_API_KEY` |
| Deploys | GitHub | `GITHUB_TOKEN` + `GITHUB_ORG` |
| Execution | Kubernetes | `KUBECONFIG_PATH` |

Unset vars activate mock fallbacks — the crew still runs.

---

## Knowledge Base

Drop markdown files into `knowledge/postmortems/` and `knowledge/runbooks/` — ingested automatically on startup.

---

## Slash Commands

```
/pagemenot triage <description>   Manually trigger a triage
/pagemenot status                 Show connected integrations
@Pagemenot <message>              Triage from any channel
```

---

## Stack

- [CrewAI](https://github.com/crewAIInc/crewAI) — multi-agent orchestration
- [Slack Bolt](https://github.com/slackapi/bolt-python) — Slack integration
- [ChromaDB](https://www.trychroma.com/) — embedded vector store
- [FastAPI](https://fastapi.tiangolo.com/) — webhook receiver
- Single container, no external services, runs on any 1GB VPS
