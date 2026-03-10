# Integrations

All integrations are optional unless noted. Configured via `.env`. If a credential is absent, the tool falls back to a mock that returns synthetic data.

## Slack (required)

| Setting | Description |
|---------|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-...` — Bot OAuth token |
| `SLACK_APP_TOKEN` | `xapp-...` — Socket Mode app token |
| `PAGEMENOT_CHANNEL` | Channel where triage results are posted (default: `incidents`) |
| `PAGEMENOT_ALERT_CHANNELS` | Channels passively monitored (default: `alerts,incidents`) |
| `PAGEMENOT_ONCALL_CHANNEL` | Escalation ping channel for high/critical alerts |

SDK: `slack-bolt>=1.20`, `slack-sdk>=3.30`. Transport: WebSocket (Socket Mode). No inbound public URL required.

## LLM Providers

| Provider | Credential | Notes |
|----------|-----------|-------|
| OpenAI | `OPENAI_API_KEY` | Default; embeddings via `text-embedding-3-small` |
| Anthropic | `ANTHROPIC_API_KEY` | No embedding API; falls back to OpenAI embeddings if key present |
| Google Gemini | `GEMINI_API_KEY` | No ChromaDB-compatible embedding; memory disabled |
| Ollama | `OLLAMA_URL` | Self-hosted; optional `OLLAMA_EMBEDDING_MODEL` for cross-incident memory |

Separate postmortem LLM: `POSTMORTEM_LLM_PROVIDER` + `POSTMORTEM_LLM_MODEL` (falls back to main LLM if unset).

## Observability

### Prometheus
- `PROMETHEUS_URL`, `PROMETHEUS_AUTH_TOKEN`
- Supports: self-hosted, AWS Managed Prometheus (AMP), Google Cloud Managed Prometheus, Grafana Cloud Prometheus

### Grafana
- `GRAFANA_URL`, `GRAFANA_API_KEY`, `GRAFANA_ORG_ID` (required for Grafana Cloud)
- Supports: self-hosted and Grafana Cloud

### Loki
- `LOKI_URL`, `LOKI_AUTH_TOKEN`, `LOKI_ORG_ID` (multi-tenant `X-Scope-OrgID`)
- Supports: self-hosted and Grafana Cloud

### Datadog
- `DATADOG_API_KEY`, `DATADOG_APP_KEY`, `DATADOG_SITE` (default: `datadoghq.com`)

### New Relic
- `NEWRELIC_API_KEY`, `NEWRELIC_ACCOUNT_ID`

## Alerting / On-call

### PagerDuty
- `PAGERDUTY_API_KEY` — REST API key; used to create and resolve incidents
- `PAGERDUTY_FROM_EMAIL` — requester email (auto-discovered from account if unset)
- Webhook: `POST /webhooks/pagerduty` (v2 format, `incident.triggered`) and `POST /webhooks/pagerduty/resolve`
- Signature verification: `X-PagerDuty-Signature` header, HMAC-SHA256, prefix `v1=`; secret: `WEBHOOK_SECRET_PAGERDUTY`

### OpsGenie
- `OPSGENIE_API_KEY`
- Webhook: `POST /webhooks/opsgenie`; actions: `Create`, `Acknowledge`
- Signature: `X-OG-Hash` header; secret: `WEBHOOK_SECRET_OPSGENIE`

## Issue Tracking

### Jira Service Management
- `JIRA_SM_URL`, `JIRA_SM_EMAIL`, `JIRA_SM_API_TOKEN`
- `JIRA_SM_PROJECT_KEY`, `JIRA_SM_ISSUE_TYPE`, `JIRA_SM_SERVICE_DESK_ID`, `JIRA_SM_REQUEST_TYPE_ID`
- Service desk ID and request type ID auto-discovered if unset
- Webhook: `POST /webhooks/jira` (resolve notifications); secret: `WEBHOOK_SECRET_JIRA`
- Severity gate: `PAGEMENOT_JIRA_MIN_SEVERITY` (default: `low` — all unresolved incidents)

## Source Control

### GitHub
- `GITHUB_TOKEN` (PAT), `GITHUB_ORG`
- Used for: deploy history lookup, PR correlation
- Service-to-repo mapping: `config/services.yaml` (no secrets, committed)

## Cloud Providers

### AWS
- Credential: IAM role assumed via `AWS_ROLE_ARN`; or instance profile / IRSA (no key needed)
- `AWS_REGION` — required for AWS runbook steps
- SDK: `boto3>=1.34`
- Services used: CloudWatch (`describe_alarms`, alarm state polling), SNS (subscription confirmation + alarm notifications)
- Webhook: `POST /webhooks/sns` — handles `SubscriptionConfirmation` and `Notification` (CloudWatch alarms)
- Post-exec health check: polls CloudWatch alarm state every `PAGEMENOT_VERIFY_POLL_INTERVAL` (default 15s) up to `PAGEMENOT_VERIFY_TIMEOUT` (default 300s)
- CLI (aws build target): AWS CLI v2, installed in `aws` and `cloud` Docker stages

### GCP
- Credential: `GOOGLE_APPLICATION_CREDENTIALS` — path to service account JSON; or Workload Identity on GCE/GKE
- SDK: none — runbook execution uses `gcloud` CLI subprocess calls
- Webhook: handled by `POST /webhooks/generic` (GCP Cloud Monitoring format; `state=closed` payloads are skipped)
- CLI (gcp build target): `google-cloud-cli`, installed in `gcp` and `cloud` Docker stages

### Azure
- Credentials: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`
- SDK: `azure-identity>=1.15`, `azure-mgmt-compute>=30.0` (VM Run Command)
- CLI (azure build target): `azure-cli`, installed in `azure` and `cloud` Docker stages

## Kubernetes
- `KUBECONFIG_PATH` — path inside container; mount via `docker-compose.yml` volumes
- `PAGEMENOT_EXEC_NAMESPACE` — fallback namespace for `{{ namespace }}` in exec tags
- `PAGEMENOT_SERVICE_NAMESPACES` — per-service overrides (`svc1=ns1,svc2=ns2`)
- Binary: `kubectl` v1.35.2, baked into all image stages (sha256 verified, arch-aware)
- Exec: `subprocess` calls to `kubectl`; timeout `PAGEMENOT_SUBPROCESS_TIMEOUT`

## State / Persistence

### Redis
- `REDIS_URL` (e.g. `redis://localhost:6379/0`)
- Role: approval state persistence; no TTL set on keys
- SDK: `redis[asyncio]>=5.0`
- Fallback: JSON file at `/app/data/approvals.json` → in-memory

### ChromaDB
- Embedded (default): SQLite at `CHROMA_PATH` (default `/app/data/chroma`)
- Remote: `CHROMA_HOST` + `CHROMA_PORT` — required for multi-replica deployments
- SDK: `chromadb>=0.5`

## Webhook Security

All webhook endpoints support optional HMAC-SHA256 signature verification. If secret is unset, pagemenot logs a warning and accepts unsigned requests.

| Endpoint | Header | Secret env var |
|----------|--------|---------------|
| `/webhooks/pagerduty` | `X-PagerDuty-Signature` (prefix `v1=`) | `WEBHOOK_SECRET_PAGERDUTY` |
| `/webhooks/grafana` | `X-Grafana-Signature` | `WEBHOOK_SECRET_GRAFANA` |
| `/webhooks/alertmanager` | `X-Alertmanager-Token` | `WEBHOOK_SECRET_ALERTMANAGER` |
| `/webhooks/datadog` | `X-Datadog-Signature` | `WEBHOOK_SECRET_DATADOG` |
| `/webhooks/opsgenie` | `X-OG-Hash` | `WEBHOOK_SECRET_OPSGENIE` |
| `/webhooks/newrelic` | `X-NR-Webhook-Token` | `WEBHOOK_SECRET_NEWRELIC` |
| `/webhooks/generic` | `X-Pagemenot-Signature` (prefix `sha256=`) | `WEBHOOK_SECRET_GENERIC` |
| `/webhooks/jira` | — | `WEBHOOK_SECRET_JIRA` |

Rate limiting: `slowapi`, per source IP, default `60/minute` (`PAGEMENOT_WEBHOOK_RATE_LIMIT`).

## Alertmanager (Prometheus)
- Webhook: `POST /webhooks/alertmanager` — `alerts[].status == "firing"` triggers triage
- Signature: `X-Alertmanager-Token` header; secret: `WEBHOOK_SECRET_ALERTMANAGER`
