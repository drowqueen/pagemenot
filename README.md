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

### 1. Slack app

1. Go to https://api.slack.com/apps → **Create New App** → **From manifest**
2. Paste:
   ```yaml
   display_information:
     name: Pagemenot
   features:
     slash_commands:
       - command: /pagemenot
         url: https://<your-host>/slack/events
         description: Triage an incident
     bot_user:
       display_name: Pagemenot
   oauth_config:
     scopes:
       bot:
         - app_mentions:read
         - channels:history
         - channels:read
         - chat:write
         - commands
         - groups:history
   settings:
     event_subscriptions:
       bot_events:
         - app_mention
         - message.channels
     interactivity:
       is_enabled: true
     socket_mode_enabled: true
   ```
3. **Install to workspace** → copy **Bot Token** (`xoxb-…`)
4. **Basic Information → App-Level Tokens** → generate token with `connections:write` scope → copy **App Token** (`xapp-…`)

### 2. LLM

Pick one provider and set its key:

| Provider | Vars |
|----------|------|
| OpenAI | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` |
| Anthropic | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` |
| Gemini | `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` |
| Ollama | `LLM_PROVIDER=ollama` + `OLLAMA_URL` |

### 3. Run

```bash
cp .env.example .env
# Fill in SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and one LLM key
docker compose up -d
```

### 4. Test without real monitoring

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
