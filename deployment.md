# Pagemenot POC — Proof of Concept Deployment Guide

## Philosophy: Run Anywhere, Mock Everything First

Pagemenot is cloud-agnostic by design. The POC runs entirely with **mock incidents**
so you can demo it without connecting real monitoring. Then you plug in real tools
one at a time.

```
                    ┌─────────────────────────┐
                    │      YOUR LAPTOP         │
                    │  docker compose up -d    │
                    │  (mock mode, no cloud)   │
                    └────────────┬─────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
          ▼                      ▼                      ▼
   ┌──────────────┐    ┌──────────────┐    ┌────────────────────┐
   │  AWS Free     │    │  GCP Free     │    │  Hetzner / DO /    │
   │  t3.micro     │    │  e2-micro     │    │  Bare metal        │
   │  750h/month   │    │  always free  │    │  Any Linux box     │
   └──────────────┘    └──────────────┘    └────────────────────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    All run the SAME docker compose
                    No cloud-specific code anywhere
```

## Quick Start (Laptop, Zero Cost)

```bash
git clone https://github.com/yourname/pagemenot.git
cd pagemenot

# Mock mode — no API keys needed for the demo!
cp .env.example .env
# Just set SLACK tokens and an LLM key
# Edit: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, OPENAI_API_KEY

docker compose up -d

# Fire a mock incident
python scripts/simulate_incident.py payment-500s

# Watch the crew triage it in Slack ✨
```

## Deployment Options (All Use the Same Docker Image)

### Option 1: AWS Free Tier (t3.micro, 750h/month free)

```bash
# One-liner: launch EC2 + install Docker + clone + run
# Uses user-data script — instance boots ready to go

aws ec2 run-instances \
  --image-id ami-0c02fb55956c7d316 \
  --instance-type t3.micro \
  --key-name your-key \
  --security-group-ids sg-xxxxxxxx \
  --user-data file://deploy/aws-userdata.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pagemenot}]' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"DeleteOnTermination":true}}]'
```

Cost: **$0/month** within free tier (1 instance, 24/7)

### Option 2: GCP Free Tier (e2-micro, always free)

```bash
gcloud compute instances create pagemenot \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=ubuntu-2404-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --metadata-from-file=startup-script=deploy/gcp-startup.sh \
  --tags=pagemenot
```

Cost: **$0/month** (e2-micro is always-free in select regions)

### Option 3: Hetzner (cheapest real server)

```bash
# CX22: 2 vCPU, 4GB RAM, €3.99/month — runs Pagemenot perfectly
hcloud server create \
  --name pagemenot \
  --type cx22 \
  --image ubuntu-24.04 \
  --ssh-key your-key \
  --user-data-from-file deploy/generic-userdata.sh
```

### Option 4: DigitalOcean

```bash
doctl compute droplet create pagemenot \
  --image ubuntu-24-04-x64 \
  --size s-1vcpu-1gb \
  --region nyc1 \
  --ssh-keys your-key-id \
  --user-data "$(cat deploy/generic-userdata.sh)"
```

### Option 5: Any Linux Box (Bare Metal, Raspberry Pi, VPS, etc.)

```bash
ssh your-server
curl -fsSL https://get.docker.com | sh
git clone https://github.com/yourname/pagemenot.git
cd pagemenot && cp .env.example .env
# Edit .env with your tokens
docker compose up -d
```

**That's it. Same 4 commands everywhere.**

## Runbooks

Runbooks are **not included in the image**. You supply your own at runtime.

### Option 1 — Local disk (default)

The default `docker-compose.yml` mounts `./knowledge/runbooks` into the container:

```yaml
volumes:
  - ./knowledge/runbooks:/app/knowledge/runbooks:ro
  - ./knowledge/postmortems:/app/knowledge/postmortems
```

Drop runbooks into `./knowledge/runbooks/<provider>/` and restart (or trigger a re-ingest):

```bash
# Re-ingest without restart
docker exec pagemenot python3 -c "from pagemenot.rag import ingest_all; ingest_all()"

# Or restart (also triggers ingest_all on startup)
docker compose restart pagemenot
```

Provider subdirectories: `aws/`, `gcp/`, `azure/`, `k8s/`, `onprem/`, `hetzner/`, `generic/`

### Option 2 — Cloud bucket

Set `PAGEMENOT_RUNBOOK_BUCKET` in `.env`. The container syncs the bucket to `/app/knowledge/runbooks` on every startup.

| Provider | Format | CLI required |
|----------|--------|-------------|
| GCS | `gs://bucket/path` | `gsutil` (included in `gcp`/`cloud` image targets) |
| S3 | `s3://bucket/path` | `aws` (included in `aws`/`cloud` image targets) |
| Azure Blob | `az://storageaccount/container` | `azcopy` (must be in PATH) |

```bash
# GCS example
PAGEMENOT_RUNBOOK_BUCKET=gs://my-org-runbooks/pagemenot

# S3 example
PAGEMENOT_RUNBOOK_BUCKET=s3://my-org-runbooks/pagemenot

# Azure Blob example (azcopy must be installed; authenticate with azcopy login or managed identity)
PAGEMENOT_RUNBOOK_BUCKET=az://mystorageaccount/runbooks
```

The bucket is synced (with delete) so the container always mirrors the bucket. Update runbooks in the bucket, then restart the container.

### Runbook format

```markdown
---
service: my-service
tags: aws, ec2, nginx
cloud_provider: aws
---

## Diagnosis

<!-- exec: aws ec2 describe-instances --instance-ids {{ service }} -->

## Resolution

<!-- exec:approve: aws ec2 start-instances --instance-ids {{ service }} -->
```

- `<!-- exec: ... -->` — runs automatically (diagnosis steps; runs before the approval prompt)
- `<!-- exec:approve: ... -->` — requires human approval via Slack button; multiple steps run sequentially on a single approval click
- `{{ service }}` and `{{ resource_group }}` are substituted at runtime

### Slow-starting services (VMs, databases, servers)

Some operations — starting a stopped database, restarting a VM — take 2-5 minutes. The default
`PAGEMENOT_AZ_TIMEOUT` (360s) covers these. For operations that block until completion (e.g.
`az postgres flexible-server start` with no flags), use `--no-wait` followed by a dedicated wait
step so pagemenot gets a real confirmation the service is healthy:

```markdown
## Resolution

<!-- exec:approve: az postgres flexible-server start --name {{ service }} --resource-group {{ resource_group }} --no-wait -->

<!-- exec:approve: az postgres flexible-server wait --name {{ service }} --resource-group {{ resource_group }} --custom "state=='Ready'" --interval 15 --timeout 300 -->
```

Both steps run sequentially after a single Slack approval click. The wait step polls every 15s for
up to 300s — the incident resolves only after the wait confirms the service is healthy.

| Env var | Default | When to raise |
|---------|---------|---------------|
| `PAGEMENOT_AZ_TIMEOUT` | 360 | Raise if `az ... wait --timeout N` and N > 300 |
| `PAGEMENOT_AZ_READ_TIMEOUT` | 30 | Read-only `az ... show/list` commands |
| `PAGEMENOT_SUBPROCESS_TIMEOUT` | 30 | kubectl / aws / shell commands |

The same pattern works for other slow Azure resources (`az vm start`, `az sql db resume`, etc.).

## Triage Behavior

### Alert lifecycle

```
Alert fires
  │
  ├─ Low severity or duplicate within TTL → suppressed, no action
  │
  └─ Crew runs
       │
       ├─ Auto-resolved (runbook exec succeeded)
       │    └─ Posts result to Slack thread. No Jira. No PD.
       │
       ├─ Crew has remediation steps, no human approval needed
       │    └─ Posts steps to Slack thread. No Jira. No PD. No oncall ping.
       │
       ├─ Crew has needs-approval steps OR no steps at all (high/critical only)
       │    └─ Opens Jira ticket (once). Pages PagerDuty (once). Pings oncall channel (once).
       │
       └─ Unresolved, medium or lower severity
            └─ Posts analysis to Slack thread. No Jira. No PD.
```

### Escalation gate

| Condition | Jira | PagerDuty | Oncall ping |
|-----------|------|-----------|-------------|
| Auto-resolved | ✗ | ✗ | ✗ |
| Crew has runbook steps (exec disabled) | ✗ | ✗ | ✗ |
| Crew needs human approval — high/critical | ✓ once | ✓ once | ✓ once |
| Crew stumped — high/critical | ✓ once | ✓ once | ✓ once |
| Crew stumped — medium/low | ✗ | ✗ | ✗ |

### Auto-resolve (monitoring-system resolves)

When `alertmanager status=resolved` or `pagerduty incident.resolved` arrives:
- Clears the alert from the dedup registry (future occurrences trigger fresh triage)
- Looks up any open Jira ticket for that alert; adds resolution comment and transitions to Done/Resolved/Closed
- Posts outcome to Slack

### Jira deduplication

One Jira ticket per incident lifecycle. If the dedup TTL expires and the same alert fires again while a Jira ticket is already open, the existing ticket is referenced instead of opening a new one. Same for PagerDuty paging.
