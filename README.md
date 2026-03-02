# Pagemenot — AI On-Call Copilot

**The problem:** An alert fires at 3am. An engineer wakes up, runs the same kubectl commands, checks the same metrics, reads the same runbook, applies the same fix. This happens hundreds of times a year for the same dozen incident types.

**What pagemenot does:** When an alert fires, a 3-agent AI crew investigates in parallel — pulling metrics, checking recent deploys, matching runbooks — and either fixes the incident autonomously or hands off to the on-call engineer with the investigation already done.

- If the crew resolves it: nobody gets paged. A summary posts to Slack.
- If the crew needs a human decision: **Approve/Reject buttons** appear in the Slack thread for risky steps. A Jira ticket opens. PagerDuty pages the on-call.
- If the crew is stumped: the on-call wakes up to a thread with root cause, correlated metrics, and the likely offending deploy already identified.

Self-hosted. No new infrastructure. Connects to your existing monitoring stack.

---

## Features

- **3-agent AI crew** — monitor, diagnose, and remediate in parallel on every alert
- **Autonomous runbook execution** — `<!-- exec: -->` tagged steps run automatically; risky steps gate on human approval
- **Learns from every incident** — postmortems indexed into ChromaDB; recurring incidents auto-resolve without pages over time
- **Approval buttons in Slack** — one click to approve or reject; approval state persists across restarts (Redis or file fallback)
- **Severity-based escalation** — Jira for all unresolved, PagerDuty + escalation channel for high/critical; fully configurable
- **Clickable escalation links** — #escalated messages link directly to the exact alert thread and Jira ticket
- **Works with any LLM** — Ollama (self-hosted, air-gapped), OpenAI, Anthropic, Gemini; switch with one env var
- **Connects to your stack** — Prometheus, Grafana, Loki, Datadog, New Relic, PagerDuty, OpsGenie, Jira, GitHub, Kubernetes
- **Webhook receiver** — Grafana, Alertmanager, Datadog, New Relic, PagerDuty, CloudWatch, Azure Monitor, generic
- **No new infrastructure** — single Docker container; ChromaDB embedded by default

## Screenshots

| Escalation — Jira + PagerDuty | Approval button | Triage thread — RCA + links | Approval detail |
|---|---|---|---|
| [![escalation](screenshots/escalation-jira-pd.png)](screenshots/escalation-jira-pd.png) | [![approval](screenshots/approval-button.png)](screenshots/approval-button.png) | [![triage](screenshots/triage-thread-rca.png)](screenshots/triage-thread-rca.png) | [![approval-detail](screenshots/approval-required-detail.png)](screenshots/approval-required-detail.png) |

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
- [Jira lifecycle](#jira-lifecycle)
- [Rate limiting](#rate-limiting)
- [Knowledge base](#knowledge-base)
- [Simulate incidents](#simulate-incidents)
- [Deploy](#deploy) · [Storage](#storage-chromadb--approvals)
- [Security](#security)
- [Cloud IAM](#cloud-iam) (AWS · GCP · Azure alerts)
- [Slash commands](#slash-commands)
- [Stack](#stack)

---

## How it works

An alert fires. Pagemenot receives it via webhook, deduplicates it (same service + alert within a TTL window is suppressed), and checks severity. If it passes those gates, three agents run simultaneously:

- **MonitorAgent** pulls the metrics, dashboards, and logs from the window surrounding the incident — whatever is configured (Prometheus, Grafana, Datadog, Loki, New Relic).
- **DiagnoserAgent** checks GitHub for deploys and PR diffs that landed before the alert fired, and searches ChromaDB for past incidents with similar symptoms.
- **RemediatorAgent** retrieves the matching runbook via RAG and attempts to execute its remediation steps.

Once the crew finishes, pagemenot decides what to do based on what the crew found:

- **Auto-resolved**: runbook steps ran, incident cleared. Slack summary posted. No Jira. No PD page.
- **Needs human approval**: crew identified a risky step (rollback, scale-down, delete). Approve/Reject buttons appear in Slack as a top-level message. Jira ticket opened (all severities — Jira emails the team). High/critical: also PD page + escalation channel ping.
- **Stumped (any severity)**: Jira ticket opened (Jira emails the team). High/critical: also PD + escalation channel with Jira and PD links.

**Escalation stack by severity:**

| Severity | Jira ticket | PagerDuty | Escalation channel |
|----------|-------------|-----------|-------------------|
| low | — | — | — |
| medium | — | — | — |
| high | ✅ | ✅ | ✅ with links |
| critical | ✅ | ✅ | ✅ with links |

Configurable: `PAGEMENOT_JIRA_MIN_SEVERITY` (default: `high`) and `PAGEMENOT_PD_MIN_SEVERITY` (default: `high`).

Low/medium unresolved incidents are posted to Slack only — no Jira ticket, no page.

When the incident resolves (monitoring system sends `status=resolved`), pagemenot closes the Jira ticket, clears the dedup window, and posts the outcome.

```
Alert (Grafana / Alertmanager / PagerDuty / Datadog / New Relic / Slack)
  │
  ▼
Dedup + severity gate ── duplicate within TTL or low severity? → suppress
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
Crew result?
  ├─ [AUTO-SAFE] steps, exec succeeds
  │    └─ ✅ Resolved — Slack summary posted. No Jira. No page.
  │
  ├─ [NEEDS APPROVAL] steps (risky: rollback, scale-down, delete)
  │    ├─ Approval gate ON  → ✅ Approve / ❌ Reject buttons (top-level Slack message)
  │    └─ Approval gate OFF → steps execute automatically
  │    + always: Jira ticket opened (Jira emails team)
  │    + high/critical: PagerDuty paged + escalation channel ping
  │
  ├─ Crew stumped (any severity)
  │    ├─ always: Jira ticket opened (Jira emails team)
  │    └─ high/critical: PagerDuty + escalation channel with Jira + PD links
  │
  └─ Auto-resolved
       └─ ✅ Slack summary. No Jira. No page.
```

When the monitoring system sends a resolve event (`status=resolved` or `incident.resolved`), pagemenot closes the open Jira ticket, clears the dedup registry, and posts the outcome to Slack.

No integrations configured → mock layer activates. Crew runs end-to-end with simulated data.

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker | 24+ | Compose v2 (`docker compose`) required |
| Slack workspace | — | Bot token + app-level token (Socket Mode) |
| LLM | — | One of: Ollama (local), OpenAI, Anthropic, Gemini |
| **Ollama (local)** | 0.3+ | Models: `ollama pull llama3.1` + `ollama pull nomic-embed-text` |
| **OpenAI** | — | `OPENAI_API_KEY` — requires signed enterprise DPA |
| **Anthropic** | — | `ANTHROPIC_API_KEY` — requires signed enterprise DPA |
| **Gemini** | — | `GEMINI_API_KEY` — requires signed enterprise DPA |
| Kubernetes (optional) | kubectl ≥ 1.28 | mount host binary + kubeconfig — see docker-compose.yml comments |
| Prometheus/Grafana (optional) | — | URLs set in `.env` |

> **Recommended for self-hosted/air-gapped:** Ollama with `llama3.1` (LLM) + `nomic-embed-text` (embeddings). No data leaves your network.

### Compute requirements

**Pagemenot container** (the SRE agent): 256 MB RAM, 0.25 vCPU. Stateless apart from the ChromaDB volume.

**Ollama** (if self-hosted LLM): requires a separate host with sufficient VRAM to load the model. A 3-agent crew makes ~15-20 LLM calls per incident; triage latency is determined by token throughput.

| Instance | Cloud | vRAM / RAM | Triage time (llama3.1 8B) |
|----------|-------|-----------|--------------------------|
| g4dn.xlarge | AWS | 16 GB GPU (T4) | ~2 min |
| g5.xlarge | AWS | 24 GB GPU (A10G) | ~1 min |
| n1-standard-4 + T4 | GCP | 16 GB GPU | ~2 min |
| Standard_NC4as_T4_v3 | Azure | 16 GB GPU (T4) | ~2 min |
| GX2-15 | Hetzner | 16 GB GPU (RTX 4000) | ~2 min |
| CPU-only (any cloud) | — | 8–16 GB RAM | 15–30 min, not recommended |

Use `llama3.2:3b` for ~3× faster inference at some reasoning quality cost, or switch to an API LLM (OpenAI, Anthropic, Gemini) for 30–60s triage without a GPU.

### Deployment topology

Pagemenot requires a **persistent process** (Slack Socket Mode needs a long-lived connection) — Lambda, Cloud Functions, and Cloud Run with `min-instances=0` will not work.

| Platform | Instance type | Notes |
|----------|--------------|-------|
| AWS ECS (Fargate) | 0.25 vCPU / 512 MB | pagemenot only; Ollama on separate EC2 GPU instance |
| AWS EC2 | t3.small+ | collocate pagemenot + Ollama on GPU instance |
| GCP Cloud Run | `--min-instances 1`, 512 MB | persistent; Ollama on separate GCE GPU VM |
| GCP GKE | 1 replica, 256m CPU / 512 MB | GPU node pool for Ollama |
| Azure Container Apps | 0.25 vCPU / 0.5 GB, min=1 | persistent; Ollama on separate ACI GPU |
| Kubernetes (any) | 1 replica; GPU node pool for Ollama | tolerations for GPU node required |
| Hetzner CX22 + GX2-15 | €4 + €35/mo | cheapest GPU-enabled setup |
| DigitalOcean Basic + GPU Droplet | $6 + $0.80/hr | GPU Droplet on-demand when needed |

> Ollama and pagemenot can run on the same GPU instance if the instance has enough VRAM for the LLM model (≥16 GB recommended for llama3.1 8B).

---

## Quick start

```bash
./setup.sh     # interactive wizard — generates .env
make install   # validates config, pulls image, starts container
make test      # fire a simulated incident
```

`.env` is gitignored. `config/services.yaml` is committed (no secrets).

| Command | Effect |
|---------|--------|
| `make install` | validate config → pull image → start |
| `make start` / `make stop` | start / stop container |
| `make logs` | follow container logs |
| `make status` | running containers + enabled integrations |
| `make test SCENARIO=checkout-oom` | fire a simulated incident |
| `make hooks` | install git pre-commit/pre-push hooks |

### Image variant — which CLI tools to bake in

Set `PAGEMENOT_BUILD_TARGET` in `.env`, then `docker compose build && docker compose up -d`.

| Environment | `PAGEMENOT_BUILD_TARGET` | Baked in | Extra size |
|-------------|--------------------------|----------|------------|
| Kubernetes only | `base` _(default)_ | kubectl | — |
| AWS (EKS / ECS / EC2) | `aws` | kubectl + AWS CLI v2 | ~500 MB |
| GCP (GKE / GCE) | `gcp` | kubectl + gcloud | ~400 MB |
| Azure (AKS) | `azure` | kubectl + Azure CLI | ~300 MB |
| Multi-cloud | `cloud` | kubectl + all three | ~1.2 GB |

kubectl is always included — it auto-detects `amd64` / `arm64` at build time. Cloud CLI credentials are still mounted at runtime via volumes or env vars (see comments in `docker-compose.yml`).

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

The LLM is the reasoning engine for all three agents — it decides which tools to call, interprets raw metrics and logs, correlates deploys with symptoms, and produces root cause analysis and remediation steps. Without it the agents cannot function.

**Cross-incident memory (Ollama)**

By default, Ollama runs without cross-incident memory. Each incident is investigated from scratch. To enable memory, pull a local embedding model and set `OLLAMA_EMBEDDING_MODEL`:

```bash
ollama pull nomic-embed-text
```

```
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

With this set, pagemenot stores past incident context in ChromaDB and the DiagnoserAgent can recognise recurring patterns across incidents. Without it, single-incident triage works fully — only the cross-run pattern matching is unavailable. OpenAI enables memory automatically via `text-embedding-3-small`.

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
| Deploy mapping | Monorepo / name mismatch | `config/services.yaml` |
| Execution | Kubernetes | `KUBECONFIG_PATH` |
| Ticketing | Jira Service Management | `JIRA_SM_URL` + `JIRA_SM_EMAIL` + `JIRA_SM_API_TOKEN` |
| Alerts | Azure Monitor | Action Group → Webhook → `/webhooks/generic` |

### `config/services.yaml`

Maps service names to GitHub repos for deploy correlation. Safe to commit — no secrets. Hot-reloaded on change. See the file for annotated examples (name mismatch, monorepo, multi-repo).

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
| `PAGEMENOT_EXEC_DRY_RUN` | `true` | `true` = simulate (log only); `false` = live execution |
| `PAGEMENOT_EXEC_NAMESPACE` | `production` | k8s namespace for `{{ namespace }}` in exec tags |

**The agent only executes what is scripted in runbooks.** The LLM reasons over the runbook and decides which steps to run, but it cannot generate or modify the commands — it can only trigger steps that already exist as `<!-- exec: -->` tags in your runbook files. If a command is not in a runbook, it does not execute.

**Dry run mode** (`PAGEMENOT_EXEC_DRY_RUN=true`, the default) simulates every step without executing anything. Each step posts its output to Slack so you can verify what *would* happen:

```
⚙️ user-service — Step 1/4: kubectl logs -n demo -l app=user-service --tail=100
✅ Step 1/4 done:
   [DRY RUN] would execute: kubectl logs -n demo -l app=user-service --tail=100

⚙️ user-service — Step 3/4: kubectl rollout restart deployment/user-service -n demo
✅ Step 3/4 done:
   [DRY RUN] would execute: kubectl rollout restart deployment/user-service -n demo
```

Set `PAGEMENOT_EXEC_DRY_RUN=false` to run commands live. All other behaviour — Slack messages, Jira tickets, PagerDuty pages, approval buttons — is identical in both modes.

---

## Approval gate

When the crew flags a step as `[NEEDS APPROVAL]` (risky operations: rollbacks, scale-down, delete), pagemenot posts **✅ Approve & Execute** / **❌ Reject** buttons as a top-level Slack message — immediately visible, not buried in a thread.

| `PAGEMENOT_APPROVAL_GATE` | Behaviour |
|--------------------------|-----------|
| `true` (default) | Buttons posted; step waits for human decision |
| `false` | `[NEEDS APPROVAL]` steps execute automatically without confirmation |

**On Approve:** steps execute, outcome posted to Slack, postmortem written to `knowledge/postmortems/` and indexed in ChromaDB.

**On Reject:** steps logged as rejected, incident stays open.

**How the crew learns from approvals (works with Ollama):**

When a human approves a risky step and it succeeds, the postmortem is indexed in ChromaDB. On the next similar incident, the DiagnoserAgent retrieves that postmortem as context. The LLM sees *"this rollback was approved and resolved the incident"* and reclassifies the same step as `[AUTO-SAFE]`. Over time, routinely approved remediations (rollbacks, restarts, scale adjustments) execute automatically without human confirmation. This is context-based learning (RAG), not model fine-tuning — it works identically with Ollama.

**Postmortem indexing (full picture):**

Postmortems are written and indexed in two cases — not just approvals:

| Trigger | Postmortem written | Indexed in ChromaDB |
|---------|-------------------|---------------------|
| Crew auto-resolves (all exec steps succeed) | ✅ | ✅ immediately |
| Human approves + execution succeeds | ✅ | ✅ immediately |
| Crew stumped / exec fails | ✅ (pending review) | ✅ on next restart |

On the next similar incident, `DiagnoserAgent` queries the `incidents` collection and injects matching postmortems as context. The effect compounds:

- **Incident 1:** human approves a rollback → postmortem written
- **Incident 2:** LLM sees prior approval in context → may classify rollback as `[AUTO-SAFE]` → no human needed
- **Incident 5+:** recurring failure type fully auto-resolves with no pages, no tickets

This is RAG (retrieval-augmented generation), not model fine-tuning. The LLM weights never change. It works identically with Ollama, OpenAI, or any other provider. The knowledge lives in ChromaDB alongside your runbooks.

**Postmortem quality matters.** The `service`, `root_cause`, and `resolution` fields drive RAG retrieval accuracy. Drop structured postmortems into `knowledge/postmortems/` to pre-seed the knowledge base before your first incident.

**Approval state persistence:**

Pagemenot uses a three-tier store for pending approvals — no approval is lost on container restart:

| Store | When active | Notes |
|-------|-------------|-------|
| Redis | `REDIS_URL` is set | Recommended for production; survives restarts and multi-instance deploys |
| JSON file | No Redis | Writes to `/app/data/approvals.json` (on the `chromadata` volume); survives restarts |
| In-memory | Neither | Lost on restart; only suitable for local testing |

Approvals never expire. An on-call engineer can wake up, see the button in Slack, and click it hours or days later.

**Recommended:** add `redis://redis:6379/0` to `.env` and a Redis service to `docker-compose.yml` for production deployments.

| Setting | Default | Effect |
|---------|---------|--------|
| `PAGEMENOT_APPROVAL_GATE` | `true` | `false` = skip approval, execute automatically |
| `REDIS_URL` | unset | Persist approval state in Redis (recommended for production) |

---

## Jira lifecycle

Jira tickets open only when the crew cannot resolve the incident (escalation gate). One ticket per incident lifecycle — duplicates within the TTL reference the existing ticket.

| Condition | Jira |
|-----------|------|
| Crew auto-resolved (any severity) | ✗ |
| Unresolved — low/medium | ✗ |
| Unresolved — high/critical | ✓ open once |

When the monitoring system sends `status=resolved` (alertmanager) or `incident.resolved` (PagerDuty), pagemenot:

1. Closes the open Jira ticket (transitions to Done/Resolved/Closed, adds resolution comment)
2. Clears the dedup registry (future occurrences trigger fresh triage)
3. Clears PD tracking
4. Posts outcome to Slack

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

**SSM exec tags** — run diagnostic commands on EC2 instances without SSH or a bastion:

```
<!-- exec: ssm:i-1234567890abcdef0 journalctl -u {{ service }} --no-pager -n 100 -->
<!-- exec: ssm:i-1234567890abcdef0 systemctl status {{ service }} -->
<!-- exec: ssm:i-1234567890abcdef0 df -h -->
```

Requires `AWS_ROLE_ARN` with SSM permissions. SSM agent must be running on the instance.

Only `<!-- exec: -->` tags execute — never free-form LLM output.

---

## Simulate incidents

Start with `PAGEMENOT_EXEC_DRY_RUN=true` (the default). The crew runs fully end-to-end — it matches runbooks, produces remediation steps, and posts results to Slack — but no real commands execute. You can verify the full triage flow, approval buttons, and Jira/PagerDuty behavior before enabling live execution.

```bash
# Recommended first run: OOM scenario with runbook exec steps
python scripts/simulate_incident.py checkout-oom
# → crew matches oomkill-response.md runbook, executes kubectl describe/get in dry-run
# → if steps are [AUTO-SAFE] and exec succeeds: auto-resolved, no Jira
# → watch: docker compose logs -f pagemenot

# High-risk scenario: deployment rollback requires human approval
python scripts/simulate_incident.py payment-500s
# → crew matches rollback-procedure.md, flags rollback as [NEEDS APPROVAL]
# → Approve/Reject buttons appear in Slack thread
# → Jira ticket opened, PagerDuty paged

python scripts/simulate_incident.py db-connection-pool
python scripts/simulate_incident.py --random
python scripts/simulate_incident.py payment-500s --source grafana
python scripts/simulate_incident.py payment-500s --source datadog
```

---

## Deploy

Runs on any host with Docker — VPS, on-prem server, cloud VM, Kubernetes, ECS, Cloud Run.

```bash
./setup.sh     # generates .env
make install   # pull image, start
```

> **First startup is slow** — ChromaDB downloads a ~80MB ONNX embedding model on first boot. Cached in a Docker volume (`chromacache`) so subsequent restarts are fast.

| Platform | Notes |
|----------|-------|
| Any Linux server | `docker compose up -d` |
| Kubernetes | 1-replica Deployment, env from Secret |
| AWS ECS / Fargate | Push to ECR, min 0.5 vCPU / 512MB |
| GCP Cloud Run | `--min-instances 1` required (Socket Mode needs persistent connection) |

Not suitable for FaaS (Lambda, Cloud Functions) — Slack Socket Mode requires a persistent connection.

### Storage (ChromaDB + approvals)

Pagemenot needs two persistent stores: the vector database (ChromaDB) and approval state.

**Single replica (default — embedded)**

```
Docker volume: chromadata
  ├─ /app/data/chroma        ← ChromaDB SQLite + ONNX cache
  └─ /app/data/approvals.json ← approval state fallback
```

Works out of the box. `CHROMA_HOST` is unset → ChromaDB runs embedded.

**Multi-replica (ECS, K8s with >1 pod)**

Embedded SQLite on shared EFS/NFS is unsafe for concurrent writes. Run a dedicated ChromaDB server:

```
┌──────────────────────────────────────────────────┐
│  pagemenot pod ×N                                 │
│    CHROMA_HOST=chromadb                           │
│    CHROMA_PORT=8000                               │
│    REDIS_URL=redis://redis:6379/0                 │
└───────────────────┬──────────────────────────────┘
                    │ HTTP
        ┌───────────▼───────────┐   ┌──────────────┐
        │  ChromaDB server      │   │  Redis        │
        │  chromadb/chroma:0.5  │   │  (approvals)  │
        │  EBS/pd-ssd volume    │   │               │
        └───────────────────────┘   └──────────────┘
```

| Setting | Default | Effect |
|---------|---------|--------|
| `CHROMA_HOST` | unset | Embedded mode (single replica) |
| `CHROMA_PORT` | `8000` | ChromaDB server port |
| `REDIS_URL` | unset | Approval state (falls back to JSON file) |

For Kubernetes, add ChromaDB as a StatefulSet with a `ReadWriteOnce` PVC. For ECS, run ChromaDB as a sidecar or separate task on a single EC2 instance with an attached EBS volume.

---

## Security

**TLS** — run pagemenot behind a reverse proxy (nginx, Caddy, ALB, GCP Load Balancer) that terminates TLS. Never expose port 8080 directly.

**HMAC signature verification** — set `WEBHOOK_SECRET_<SOURCE>` for each alerting tool. Pagemenot rejects requests with invalid signatures. Unset = warn and accept (dev only).

**IP allowlisting** — optionally restrict inbound webhook traffic to published IP ranges of your alerting tools:

| Tool | IP ranges |
|------|-----------|
| PagerDuty | [pagerduty.com/docs/ip-safelisting](https://support.pagerduty.com/docs/ip-safelisting) |
| Grafana Cloud | [grafana.com/docs/grafana-cloud/account-management/ip-addresses](https://grafana.com/docs/grafana-cloud/account-management/ip-addresses/) |
| Datadog | [docs.datadoghq.com/api/latest/ip-ranges](https://docs.datadoghq.com/api/latest/ip-ranges/) |
| New Relic | [docs.newrelic.com/docs/new-relic-solutions/get-started/networks](https://docs.newrelic.com/docs/new-relic-solutions/get-started/networks/) |
| Alertmanager | Self-hosted — allowlist your own Alertmanager IP |

Configure at your firewall, security group, or load balancer — not in pagemenot itself.

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
          "logs:DescribeLogGroups", "logs:DescribeLogStreams",
          "ssm:SendCommand", "ssm:GetCommandInvocation",
          "ssm:DescribeInstanceInformation"
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
| [ChromaDB](https://www.trychroma.com/) | vector store (embedded or remote via `CHROMA_HOST`) |
| [FastAPI](https://fastapi.tiangolo.com/) | webhook receiver |
| [Ollama](https://ollama.com) | self-hosted LLM option |
