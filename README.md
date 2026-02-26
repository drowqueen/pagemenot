# Pagemenot — AI On-Call Copilot

Open-source, self-hosted AI SRE that handles 3 AM pages so you don't have to.

Alert fires → crew triages in <60s → root cause + fix in Slack, waiting for your approval.

---

## Architecture

```
Alert (PagerDuty / Grafana / Alertmanager / curl)
        │
        ▼
┌───────────────────────────────────────────────┐
│  FastAPI  /webhooks/*                         │
│  Slack Bot  /pagemenot triage "..."           │
└───────────────┬───────────────────────────────┘
                │
                ▼
        ┌───────────────┐
        │   Supervisor  │  (CrewAI hierarchical process)
        └───────┬───────┘
        ┌───────┼───────┐
        ▼       ▼       ▼
   ┌────────┐ ┌─────────────┐ ┌────────────┐
   │Monitor │ │  Diagnoser  │ │ Remediator │
   └───┬────┘ └──────┬──────┘ └─────┬──────┘
       │             │              │
  Prometheus    GitHub deploys   Runbook RAG
  Grafana        PR diffs        kubectl rollback
  Loki logs      Incident RAG    Human approval
  PagerDuty      (ChromaDB)      gate
       │
       └──────────────────────────────▶ Slack thread
                                        (with approve/reject)
```

**Data flow:** Alert → parse → seed mock if no live integrations → crew kickoff → structured result → Slack thread with approval buttons.

---

## Quick Start

```bash
cp .env.example .env
# Fill in SLACK_BOT_TOKEN, SLACK_APP_TOKEN, OPENAI_API_KEY (minimum)
docker compose up -d
```

**Demo without real monitoring (works immediately):**

```bash
python scripts/simulate_incident.py payment-500s
# Watch the crew triage it in Slack
```

Available scenarios: `payment-500s`, `checkout-oom`, `db-connection-pool`, `cert-renewal`, `traffic-spike`, `--random`

---

## How It Works

| Step | Component | What Happens |
|------|-----------|--------------|
| 1 | Webhook / Slack | Alert arrives, parsed to standard format |
| 2 | Mock layer | If no live integration, realistic mock data auto-loads |
| 3 | MonitorAgent | Pulls metrics (Prometheus), logs (Loki), alert details (PagerDuty) |
| 4 | DiagnoserAgent | Correlates with recent GitHub deploys, searches past incidents (ChromaDB RAG) |
| 5 | RemediatorAgent | Searches runbooks, proposes fix, flags for approval |
| 6 | Slack | Root cause + confidence + remediation posted in thread |
| 7 | Human gate | Engineer clicks Approve or Reject before any action executes |

---

## Integrations

Add to `.env` — each one upgrades from mock → live data. Skip any you don't have.

| Env Var | Enables |
|---------|---------|
| `PROMETHEUS_URL` | Live metrics |
| `GRAFANA_URL` + `GRAFANA_API_KEY` | Alert history |
| `LOKI_URL` | Log search |
| `PAGERDUTY_API_KEY` | Incident details |
| `GITHUB_TOKEN` + `GITHUB_ORG` | Deploy correlation, PR diffs |
| `KUBECONFIG_PATH` | Kubernetes rollback |

No integrations configured → all tools use realistic mock data. The crew still works.

---

## Knowledge Base

Drop markdown files in `knowledge/postmortems/` and `knowledge/runbooks/` — Pagemenot ingests them on startup into ChromaDB.

Sample postmortems and runbooks included. The more you add, the better the RAG retrieval.

---

## Slash Commands

```
/pagemenot triage <description>   Manually trigger a triage
/pagemenot status                 Show connected integrations
@Pagemenot <message>              Mention in any channel to triage
```

---

## Responsible AI

Every remediation action requires explicit human approval via Slack button before execution. Pagemenot never modifies infrastructure autonomously.

Full audit trail: all triage runs logged with timestamp, root cause, confidence level, and who approved or rejected each action.

---

## Results

Tested against 5 simulated incident scenarios:
- 5/5 correct root cause identification
- 5/5 relevant runbook surfaced
- 0 autonomous infrastructure changes (approval gate enforced)
- Median triage time: <60s end-to-end

---

## Stack

- [CrewAI](https://github.com/crewAIInc/crewAI) — multi-agent orchestration
- [Slack Bolt](https://github.com/slackapi/bolt-python) — Slack integration
- [ChromaDB](https://www.trychroma.com/) — vector store for RAG
- [FastAPI](https://fastapi.tiangolo.com/) — webhook receiver
- Self-hosted — your data stays on your infra
