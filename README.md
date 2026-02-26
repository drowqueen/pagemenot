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

**Slack app** (one-time): https://api.slack.com/apps → Create New App → From scratch
- OAuth scopes: `app_mentions:read` `channels:history` `channels:read` `chat:write` `commands` `groups:history`
- Event subscriptions: `app_mention` `message.channels`
- Slash commands: `/pagemenot`
- Socket Mode: enable → generate app-level token (`connections:write` scope)
- Install to workspace → paste `xoxb-…` → `SLACK_BOT_TOKEN`, `xapp-…` → `SLACK_APP_TOKEN`

**LLM** — pick one, set in `.env`:

| Provider | Data stays in | Production SRE use |
|----------|--------------|-------------------|
| Ollama (self-hosted) | Your network | Yes — recommended default |
| OpenAI Enterprise | OpenAI (with DPA) | Yes — requires `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` |
| Google Vertex AI | Google (with DPA) | Yes — requires `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` |
| OpenAI / Anthropic / Gemini (standard) | Provider API | No — dev/test only |

> ---
> **⛔ DATA PRIVACY WARNING**
>
> Agents send tool outputs — Prometheus metrics, filtered error logs, GitHub PR diffs, and runbook text — to the configured LLM.
>
> **Standard API tiers (OpenAI, Anthropic, Gemini) are not suitable for production SRE use.** Your operational data will leave your network and may be used for model training under standard terms.
>
> For production use:
> - **Self-hosted:** `LLM_PROVIDER=ollama` — nothing leaves your network
> - **External:** requires an enterprise plan with a signed DPA and zero data retention. Set `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` only after legal review.
>
> Pagemenot will refuse to start with an external LLM unless `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` is set.
> ---

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
