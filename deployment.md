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
