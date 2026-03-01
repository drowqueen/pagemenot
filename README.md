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
- [Knowledge base](#knowledge-base)
- [Simulate incidents](#simulate-incidents)
- [Deploy](#deploy)
- [AWS IAM role](#aws-iam-role)
- [Slash commands](#slash-commands)
- [Stack](#stack)

---

## How it works

```
Alert (Grafana / Alertmanager / PagerDuty / Datadog / New Relic / Slack)
  │
  ▼
Dedup + severity gate  ──── duplicate or low severity? → suppress (1-line note)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  MonitorAgent         DiagnoserAgent      RemediatorAgent │
│  Prometheus metrics   GitHub PR diffs     Runbook RAG     │
│  Grafana dashboards   Deploy history      kubectl exec    │
│  Loki logs            Past incidents      AWS read APIs   │
│  Datadog / NR         (ChromaDB)          Human gate      │
└─────────────────────────────────────────────────────────┘
  │
  ▼
Runbook matched + exec enabled?
  │
  ├─ YES → execute <!-- exec: --> steps against real cluster
  │           all succeed? → ✅ auto-resolved → Slack only, done
  │           any fail?    → escalate with execution log
  │
  └─ NO  → escalate
             #alerts channel  — triage thread + root cause + Jira ticket
             #escalated channel — loud ping + PagerDuty incident URL
             PagerDuty — pages on-call human (last resort)
```

No integrations configured → mock layer activates. Crew still runs end-to-end.

---

## Quick start

```bash
cp .env.example .env        # one file, all config
# set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, LLM keys
docker compose up -d
python scripts/simulate_incident.py payment-500s   # smoke test
```

---

## Slack app setup

1. [Create app from manifest](https://api.slack.com/apps) → **Create New App** → **From a manifest** → paste JSON below
2. **Basic Information → App-Level Tokens** → generate token, scope: `connections:write` → `SLACK_APP_TOKEN`
3. **OAuth & Permissions → Install to Workspace** → `SLACK_BOT_TOKEN`
4. Invite bot to your alerts channel: `/invite @PageMeNot`

<details>
<summary>Slack app manifest (JSON)</summary>

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

| Provider | `.env` vars | Production SRE use |
|----------|------------|-------------------|
| Ollama (self-hosted) | `OLLAMA_URL` | ✅ recommended — nothing leaves your network |
| OpenAI Enterprise | `OPENAI_API_KEY` + `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` | ✅ requires signed DPA |
| Anthropic / Gemini / OpenAI (standard) | API key + `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` | ⚠ dev/test only |

> **⛔ DATA PRIVACY**
> Agents send tool outputs — metrics, filtered error logs, PR diffs, runbook text — to the LLM.
> Standard API tiers are not suitable for production. Your data may be used for model training.
> Use Ollama, or set `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` only after legal review of your provider's DPA.

---

## Integrations

Set vars in `.env` → integration activates. Unset → mock fallback.

| Category | Tool | Required vars |
|----------|------|---------------|
| Metrics | Prometheus (self-hosted) | `PROMETHEUS_URL` |
| Metrics | AWS / GCP Managed Prometheus | `PROMETHEUS_URL` + `PROMETHEUS_AUTH_TOKEN` |
| Metrics | Datadog | `DATADOG_API_KEY` + `DATADOG_APP_KEY` |
| Metrics | New Relic | `NEWRELIC_API_KEY` + `NEWRELIC_ACCOUNT_ID` |
| Dashboards | Grafana (self-hosted) | `GRAFANA_URL` + `GRAFANA_API_KEY` |
| Dashboards | Grafana Cloud | `GRAFANA_URL` + `GRAFANA_API_KEY` + `GRAFANA_ORG_ID` |
| Logs | Loki (self-hosted) | `LOKI_URL` |
| Logs | Loki (Grafana Cloud) | `LOKI_URL` + `LOKI_AUTH_TOKEN` + `LOKI_ORG_ID` |
| On-call | PagerDuty | `PAGERDUTY_API_KEY` |
| Deploys | GitHub | `GITHUB_TOKEN` + `GITHUB_ORG` |
| Execution | Kubernetes | `KUBECONFIG_PATH` |
| Ticketing | Jira Service Management | `JIRA_SM_URL` + `JIRA_SM_EMAIL` + `JIRA_SM_API_TOKEN` |

---

## Webhook sources

Point your alerting tool at the appropriate endpoint:

| Source | Endpoint |
|--------|----------|
| PagerDuty | `POST /webhooks/pagerduty` |
| Grafana | `POST /webhooks/grafana` |
| Alertmanager | `POST /webhooks/alertmanager` |
| Datadog | `POST /webhooks/datadog` |
| New Relic | `POST /webhooks/newrelic` |
| OpsGenie / Jira SM / anything else | `POST /webhooks/generic` |

Set `WEBHOOK_SECRET_<SOURCE>` to enable HMAC signature verification. Unset = warn and accept.

---

## Autonomous execution

Off by default. Enable progressively:

```bash
PAGEMENOT_EXEC_DRY_RUN=true    # reads real alerts, logs steps, executes nothing
PAGEMENOT_EXEC_ENABLED=true    # real execution (after dry run validation)
```

Execution is gated to runbook `<!-- exec: -->` tags only — LLM output never triggers commands directly.

Allowed operations: `kubectl rollout undo`, `kubectl scale`, `kubectl get/describe/logs`, AWS read-only APIs, health check HTTP calls.

---

## Knowledge base

Drop markdown files into:

```
knowledge/runbooks/       ← operational procedures (supports <!-- exec: --> tags)
knowledge/postmortems/    ← past incident write-ups
```

Restart the container → auto-ingested into ChromaDB. No reindex command needed.

The crew searches both collections during every triage. More runbooks = better remediation suggestions.

**Runbook format** — drop any markdown file with this structure:

```markdown
# Service Name Issue Title

## Symptoms
- What firing alerts look like

## Diagnosis
1. What to check first

## Remediation

### Step 1 — Check pods
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Roll back
<!-- exec: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->

### Step 3 — Verify
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Conditions that require human intervention
```

**Template variables** substituted at runtime:

| Variable | Value |
|----------|-------|
| `{{ service }}` | detected service name from the alert |
| `{{ namespace }}` | `PAGEMENOT_EXEC_NAMESPACE` (default: `production`) |

Only `<!-- exec: -->` tags run — never free-form LLM text. Tags are extracted from runbook files before any LLM sees them.

---

## Simulate incidents

```bash
python scripts/simulate_incident.py payment-500s
python scripts/simulate_incident.py checkout-oom
python scripts/simulate_incident.py db-connection-pool
python scripts/simulate_incident.py cert-renewal
python scripts/simulate_incident.py traffic-spike
python scripts/simulate_incident.py --random

# Test specific webhook format
python scripts/simulate_incident.py payment-500s --source grafana
python scripts/simulate_incident.py payment-500s --source datadog
python scripts/simulate_incident.py payment-500s --source newrelic
python scripts/simulate_incident.py payment-500s --source alertmanager
```

---

## Deploy

Same `docker compose up -d` everywhere — no cloud-specific config.

| Platform | Free tier | Notes |
|----------|-----------|-------|
| Any Linux box / VPS | — | `curl -fsSL https://get.docker.com | sh` + clone + run |
| AWS EC2 t3.micro | 750h/month | 12-month free tier |
| GCP e2-micro | Always free | select regions |
| DigitalOcean | $200 credit / 60 days | [sign up](https://try.digitalocean.com/freetrialoffer) |
| Hetzner CX22 | ~€4/mo | cheapest paid option |
| Fly.io | Free tier | 256MB RAM |

**Observability stack (local testing)**

```bash
# Prometheus + Grafana + Loki on minikube
helm install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --set grafana.adminPassword=pagemenot
helm install loki grafana/loki-stack \
  --namespace monitoring --set grafana.enabled=false --set promtail.enabled=true

kubectl port-forward -n monitoring svc/kube-prometheus-kube-prome-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-grafana 3000:80 &
kubectl port-forward -n monitoring svc/loki 3100:3100 &
```

---

## AWS IAM role

Required when `AWS_ROLE_ARN` is set. Grants read-only access to ECS, CloudWatch, AutoScaling, ElastiCache.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed -i "s/ACCOUNT_ID/$ACCOUNT_ID/" deploy/pagemenot-trust-policy.json

aws iam create-role \
  --role-name pagemenot-exec \
  --assume-role-policy-document file://deploy/pagemenot-trust-policy.json

aws iam put-role-policy \
  --role-name pagemenot-exec \
  --policy-name pagemenot-policy \
  --policy-document file://deploy/pagemenot-iam-policy.json
```

Set `AWS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/pagemenot-exec` in `.env`.

---

## Slash commands

```
/pagemenot triage <description>   manually trigger triage
/pagemenot status                 show connected integrations
@Pagemenot <message>              triage from any channel
```

---

## Stack

| | |
|-|-|
| [CrewAI](https://github.com/crewAIInc/crewAI) | multi-agent orchestration |
| [Slack Bolt](https://github.com/slackapi/bolt-python) | Slack Socket Mode |
| [ChromaDB](https://www.trychroma.com/) | embedded vector store (RAG) |
| [FastAPI](https://fastapi.tiangolo.com/) | webhook receiver |
| [Ollama](https://ollama.com) | self-hosted LLM |

Single container. No external services. Runs on any 1GB VPS.
