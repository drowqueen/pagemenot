# Pagemenot

## What This Is

AI on-call copilot: receives alerts via webhooks or Slack, runs a 3-agent CrewAI crew (monitor → diagnose → remediate), executes runbook steps autonomously, and escalates when human judgment is needed. Self-hosted. Connects to existing monitoring stacks.

Currently supports AWS (SNS + CloudWatch), Kubernetes, New Relic, Grafana, PagerDuty. GCP support in progress.

## Core Value

An alert fires → nobody gets paged because pagemenot already fixed it and posted a Slack summary. If it can't fix it, the on-call wakes up to a thread with root cause and correlated context already done.

## Requirements

### Validated

- ✓ 3-agent CrewAI crew (monitor, diagnoser, remediator) — existing
- ✓ AWS alert ingestion via SNS webhook — existing
- ✓ CloudWatch alarm state as health signal for verification — existing
- ✓ Autonomous runbook execution (`<!-- exec: -->` tagged steps only) — existing
- ✓ Approval gate via Slack buttons (approve/reject risky steps) — existing
- ✓ Severity-based escalation: Jira (all unresolved) + PagerDuty (high/critical) — existing
- ✓ ChromaDB RAG over runbooks and postmortems — existing
- ✓ Postmortem auto-indexed on incident close — existing
- ✓ Multi-LLM support (Ollama, OpenAI, Anthropic, Gemini) — existing
- ✓ Kubernetes exec (kubectl) — existing, tested
- ✓ New Relic, Grafana, PagerDuty webhook ingestion — existing

### Active

**Bug fix (blocker for GCP)**
- [ ] RAG retrieves runbooks filtered by cloud provider — no AWS runbooks returned for GCP incidents and vice versa

**GCP support**
- [ ] GCP Cloud Monitoring alerts ingested and parsed correctly
- [ ] New Relic infra agent alerts for GCP VMs routed correctly
- [ ] gcloud CLI exec steps run from inside the pagemenot container
- [ ] Runbooks for GCE nginx stopped, GCE instance stopped, Cloud Run unavailable — exec steps verified
- [ ] GCE nginx stopped: auto-resolved end-to-end in Slack (alarm test 1)
- [ ] GCE instance stopped: auto-resolved end-to-end in Slack (alarm test 2)
- [ ] Cloud Run unavailable: auto-resolved end-to-end in Slack (alarm test 3)
- [ ] Grafana alert for GCP target: routed and handled (alarm test 4)
- [ ] README updated — GCP no longer "coming soon"
- [ ] feature/gcp-testing PR merged to main

**Future: Azure support (next milestone)**
- [ ] Azure Monitor alerts ingested via webhook
- [ ] az CLI exec support from container
- [ ] Azure runbooks with exec: steps (VM restart, App Service, etc.)

**Backlog (no committed milestone yet)**
- [ ] Escalation timeout — auto-page oncall if incident unresolved in N minutes
- [ ] SSM exec for EC2 process diagnostics (ps aux, systemctl via SSM SendCommand)
- [ ] Cross-instance dedup lock via Redis (multi-replica safety)
- [ ] Approval audit log (who approved what, when, outcome)
- [ ] Persist pending verification tasks across container restarts
- [ ] Audit exec_kubectl for unhandled failure modes
- [ ] Per-team Slack channel routing

### Out of Scope

- War room channel creation — not needed
- Status page integration (Statuspage.io, Better Uptime) — not planned
- MTTR / MTTA dashboard — not planned
- HTTP dashboard UI of any kind — not planned
- Kubernetes support — already done

## Context

- Branch: `feature/gcp-testing` — all GCP work here, merge via PR
- pagemenot VM: `34.123.60.64` (e2-small, us-central1-a) — app host
- gcp-app-vm: `34.172.81.177` (e2-micro, us-central1-a) — test target, nginx on port 80
- gcp-hello: Cloud Run, us-central1
- Image: `us-central1-docker.pkg.dev/zipintel/pagemenot/pagemenot:latest`
- **Never build Docker on the pagemenot VM** — always pull from Artifact Registry
- LLM on VM: `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-2.0-flash`
- NR infra agent on gcp-app-vm, policy `1674907`, routes to `http://34.123.60.64:8080/webhooks/newrelic`

## Constraints

- **Runtime**: No terminal-blocking commands. All long-running ops in `screen -dmS`.
- **Build**: Docker builds use Cloud Build → Artifact Registry. Never local build on VM.
- **AWS**: AWS code is final/shipped — do not touch AWS runbooks, tools, or config.
- **Branch**: All changes on `feature/gcp-testing` or `fix/*` branches; never commit to main directly.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| exec_gcp via exec_shell wrapping gcloud | No native GCP exec layer needed; gcloud CLI handles all ops | — Pending (tests in progress) |
| RAG must filter by cloud provider | Mixed runbooks cause wrong remediation steps | — Pending (bug fix phase) |
| Gemini LLM on GCP VM | Native GCP credential chain; no key management | — Pending |
| Azure after GCP stabilizes | One cloud at a time; GCP must pass all tests first | — Pending |

---
*Last updated: 2026-03-07 after initialization*
