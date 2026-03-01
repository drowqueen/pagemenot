# Pagemenot — AI On-Call Copilot

Self-hosted AI SRE. Alert fires → 3-agent crew triages → root cause + remediation posted to Slack. Executes runbook steps autonomously. Pages humans only when it can't resolve.

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Slack app setup](#slack-app-setup)
- [LLM configuration](#llm-configuration)
- [Integrations](#integrations)
- [Webhook sources](#webhook-sources)
- [Autonomous execution](#autonomous-execution)
- [Approval gate](#approval-gate)
- [Rate limiting](#rate-limiting)
- [Knowledge base](#knowledge-base)
- [Simulate incidents](#simulate-incidents)
- [Deploy](#deploy)
- [Cloud IAM](#cloud-iam) (AWS · GCP · Azure alerts)
- [Slash commands](#slash-commands)
- [Stack](#stack)

---

## How it works

```
Alert (Grafana / Alertmanager / PagerDuty / Datadog / New Relic / Slack)
  │
  ▼
Dedup + severity gate  ──── duplicate or low severity? → suppress
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  MonitorAgent         DiagnoserAgent      RemediatorAgent │
│  Prometheus metrics   GitHub PR diffs     Runbook RAG     │
│  Grafana dashboards   Deploy history      kubectl exec    │
│  Loki logs            Past incidents      AWS read APIs   │
│  Datadog / NR         (ChromaDB)                         │
└──────────────────────────────────────────────────────────┘
  │
  ▼
Runbook matched + exec enabled?
  ├─ YES → execute steps → all succeed? → ✅ auto-resolved
  │                      → any fail?   → escalate with log
  └─ NO  → escalate
             #alerts — triage thread + root cause + Jira ticket
             #oncall — loud ping + PagerDuty incident URL
```

No integrations configured → mock layer activates. Crew still runs end-to-end.

---

## Quick start

```bash
cp .env.example .env        # one file, all config
docker compose up -d
python scripts/simulate_incident.py payment-500s
```

---

## Slack app setup

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From a manifest** → paste the JSON below
2. **Basic Information → App-Level Tokens** → scope `connections:write` → `SLACK_APP_TOKEN`
3. **OAuth & Permissions → Install to Workspace** → `SLACK_BOT_TOKEN`
4. `/invite @PageMeNot` in your alerts channel

<details>
<summary>Slack app manifest</summary>

```json
{
  "display_information": { "name": "PageMeNot", "description": "AI SRE on-call copilot", "background_color": "#1a1a2e" },
  "features": {
    "bot_user": { "display_name": "PageMeNot", "always_online": true },
    "slash_commands": [{ "command": "/pagemenot", "description": "Manually trigger incident triage", "usage_hint": "triage <description> | status", "should_escape": false }]
  },
  "oauth_config": { "scopes": { "bot": ["app_mentions:read","channels:history","channels:read","chat:write","commands","groups:history"] } },
  "settings": {
    "event_subscriptions": { "bot_events": ["app_mention","message.channels"] },
    "interactivity": { "is_enabled": true },
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```
</details>

---

## LLM configuration

| Provider | `.env` vars | Notes |
|----------|------------|-------|
| [Ollama](https://ollama.com) (self-hosted) | `OLLAMA_URL` | Nothing leaves your network |
| OpenAI Enterprise | `OPENAI_API_KEY` + `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` | Requires signed DPA |
| Anthropic / Gemini / OpenAI (standard) | API key + `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` | Dev/test only |

> **⛔ DATA PRIVACY** — Agents send metrics, log snippets, PR diffs, and runbook text to the LLM. Standard API tiers may use your data for training. Use local Ollama for production or confirm a zero-retention DPA with your provider.

---

## Integrations

Set vars in `.env` → integration activates. Unset → mock fallback.

| Category | Tool | Required vars |
|----------|------|---------------|
| Metrics | Prometheus | `PROMETHEUS_URL` |
| Metrics | Prometheus (managed) | `PROMETHEUS_URL` + `PROMETHEUS_AUTH_TOKEN` |
| Metrics | Datadog | `DATADOG_API_KEY` + `DATADOG_APP_KEY` |
| Metrics | New Relic | `NEWRELIC_API_KEY` + `NEWRELIC_ACCOUNT_ID` |
| Dashboards | Grafana | `GRAFANA_URL` + `GRAFANA_API_KEY` |
| Dashboards | Grafana Cloud | `GRAFANA_URL` + `GRAFANA_API_KEY` + `GRAFANA_ORG_ID` |
| Logs | Loki | `LOKI_URL` |
| Logs | Loki (Grafana Cloud) | `LOKI_URL` + `LOKI_AUTH_TOKEN` + `LOKI_ORG_ID` |
| On-call | PagerDuty | `PAGERDUTY_API_KEY` |
| Deploys | GitHub | `GITHUB_TOKEN` + `GITHUB_ORG` |
| Execution | Kubernetes | `KUBECONFIG_PATH` |
| Ticketing | Jira Service Management | `JIRA_SM_URL` + `JIRA_SM_EMAIL` + `JIRA_SM_API_TOKEN` |
| Alerts | Azure Monitor | Action Group → Webhook → `/webhooks/generic` |

---

## Webhook sources

| Source | Endpoint |
|--------|----------|
| Grafana | `POST /webhooks/grafana` |
| Alertmanager | `POST /webhooks/alertmanager` |
| Datadog | `POST /webhooks/datadog` |
| New Relic | `POST /webhooks/newrelic` |
| PagerDuty | `POST /webhooks/pagerduty` |
| AWS CloudWatch | SNS → `POST /webhooks/generic` (via Lambda or SNS HTTP subscription) |
| GCP Alerting | Alerting policy → Webhook notification channel → `POST /webhooks/generic` |
| Azure Monitor | Action Group → Webhook → `POST /webhooks/generic` |
| OpsGenie / anything else | `POST /webhooks/generic` |

Set `WEBHOOK_SECRET_<SOURCE>` to enable HMAC verification per source. Unset = warn and accept.

---

## Autonomous execution

| Setting | Default | Effect |
|---------|---------|--------|
| `PAGEMENOT_EXEC_ENABLED` | `true` | Master switch for runbook execution |
| `PAGEMENOT_EXEC_DRY_RUN` | `true` | Log steps only — no commands run |
| `PAGEMENOT_EXEC_NAMESPACE` | `production` | k8s namespace for `{{ namespace }}` in exec tags |

Set `PAGEMENOT_EXEC_DRY_RUN=false` for live execution. Execution is gated to `<!-- exec: -->` tags in runbook files — LLM output never triggers commands directly.

Allowed: `kubectl rollout undo`, `kubectl scale`, `kubectl get/describe/logs`, AWS read-only APIs, HTTP health checks.

---

## Approval gate

`[NEEDS APPROVAL]` steps post Approve/Reject buttons in the triage thread. Default: off (steps execute automatically).

| Setting | Default | Effect |
|---------|---------|--------|
| `PAGEMENOT_APPROVAL_GATE` | `false` | `true` = require human approval for `[NEEDS APPROVAL]` steps |
| `REDIS_URL` | unset | Set to persist approvals across restarts (`redis://host:6379/0`) |

---

## Rate limiting

| Setting | Default | Effect |
|---------|---------|--------|
| `PAGEMENOT_WEBHOOK_RATE_LIMIT` | `60/minute` | Per-IP limit on all `/webhooks/*` endpoints. Exceeding returns `429`. |

Format: `N/second`, `N/minute`, `N/hour`.

---

## Knowledge base

```
knowledge/runbooks/       ← runbooks with <!-- exec: --> tags
knowledge/postmortems/    ← past incident write-ups
```

Restart → auto-ingested into ChromaDB.

**Runbook format:**

```markdown
# Service — Issue Title

## Symptoms
- alert conditions

## Diagnosis
1. what to check

## Remediation
<!-- exec: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- conditions requiring human intervention
```

| Template var | Value |
|-------------|-------|
| `{{ service }}` | service name detected from the alert |
| `{{ namespace }}` | `PAGEMENOT_EXEC_NAMESPACE` |

Only `<!-- exec: -->` tags execute — never free-form LLM output.

---

## Simulate incidents

```bash
python scripts/simulate_incident.py payment-500s
python scripts/simulate_incident.py checkout-oom
python scripts/simulate_incident.py db-connection-pool
python scripts/simulate_incident.py --random
python scripts/simulate_incident.py payment-500s --source grafana
python scripts/simulate_incident.py payment-500s --source datadog
```

---

## Deploy

Runs on any host with Docker — VPS, on-prem server, cloud VM, Kubernetes, ECS, Cloud Run.

```bash
cp .env.example .env
docker compose up -d
```

| Platform | Notes |
|----------|-------|
| Any Linux server | `docker compose up -d` |
| Kubernetes | 1-replica Deployment, env from Secret |
| AWS ECS / Fargate | Push to ECR, min 0.5 vCPU / 512MB |
| GCP Cloud Run | `--min-instances 1` required (Socket Mode needs persistent connection) |

Not suitable for FaaS (Lambda, Cloud Functions) — Slack Socket Mode requires a persistent connection.

---

## Cloud IAM

Only needed if you set `AWS_ROLE_ARN` or `GOOGLE_APPLICATION_CREDENTIALS` to let pagemenot call cloud APIs for diagnosis and execution. Skip if not using cloud execution.

### Azure Monitor alerts

No `.env` vars required. In the Azure portal:

1. **Monitor → Alerts → Action Groups** → create or edit a group
2. Add action: **Webhook**
3. URL: `https://your-pagemenot-url/webhooks/generic`
4. Enable **common alert schema**

Optionally set `WEBHOOK_SECRET_GENERIC` in `.env` — pagemenot will verify the `X-Pagemenot-Signature` header. Azure doesn't natively sign webhook payloads, so leave unset unless you add your own signing proxy.

### AWS

Pagemenot assumes an IAM role to read ECS and CloudWatch. Create the role:

```bash
aws iam create-role --role-name pagemenot-exec \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::YOUR_ACCOUNT_ID:root" },
      "Action": "sts:AssumeRole",
      "Condition": { "StringEquals": { "sts:ExternalId": "pagemenot" } }
    }]
  }'

aws iam put-role-policy --role-name pagemenot-exec \
  --policy-name pagemenot-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ecs:DescribeServices", "ecs:DescribeTasks",
          "ecs:DescribeTaskDefinition", "ecs:ListTasks", "ecs:ListServices",
          "cloudwatch:GetMetricStatistics", "cloudwatch:GetMetricData",
          "cloudwatch:ListMetrics", "cloudwatch:DescribeAlarms",
          "logs:GetLogEvents", "logs:FilterLogEvents",
          "logs:DescribeLogGroups", "logs:DescribeLogStreams"
        ],
        "Resource": "*"
      }
    ]
  }'
```

Set `AWS_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT_ID:role/pagemenot-exec` in `.env`.

### GCP

Create a Service Account with read-only access to Monitoring and Logging:

```bash
gcloud iam service-accounts create pagemenot \
  --display-name "Pagemenot SRE"

gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member "serviceAccount:pagemenot@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role "roles/monitoring.viewer"

gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member "serviceAccount:pagemenot@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role "roles/logging.viewer"

gcloud iam service-accounts keys create pagemenot-sa.json \
  --iam-account pagemenot@YOUR_PROJECT.iam.gserviceaccount.com
```

Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/pagemenot-sa.json` in `.env`.

---

## Slash commands

```
/pagemenot triage <description>   trigger triage
/pagemenot status                 show connected integrations
@Pagemenot <message>              triage from any channel
```

---

## Stack

| | |
|-|-|
| [CrewAI](https://github.com/crewAIInc/crewAI) | multi-agent orchestration |
| [Slack Bolt](https://github.com/slackapi/bolt-python) | Slack Socket Mode |
| [ChromaDB](https://www.trychroma.com/) | embedded vector store |
| [FastAPI](https://fastapi.tiangolo.com/) | webhook receiver |
| [Ollama](https://ollama.com) | self-hosted LLM option |
