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

---

## Observability Stack for Testing (Prometheus + Loki)

Two paths: **local** (minikube, free, disposable) or **cloud** (Grafana Cloud free tier, zero infra).

---

### Path A: Minikube (Local K8s — Recommended for Full Testing)

Runs kube-prometheus-stack (Prometheus + Alertmanager + Grafana) + Loki on your laptop.
Alertmanager fires webhooks directly to pagemenot. Tests the full incident pipeline.

**Prerequisites**

```bash
# macOS
brew install minikube helm kubectl

# Linux
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
# helm: https://helm.sh/docs/intro/install/
# kubectl: https://kubernetes.io/docs/tasks/tools/
```

**1. Start minikube**

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
```

**2. Install Prometheus + Alertmanager + Grafana**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

kubectl create namespace monitoring

helm install kube-prom prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=pagemenot \
  --set alertmanager.alertmanagerSpec.externalUrl=http://localhost:9093
```

**3. Install Loki + Promtail**

```bash
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --set grafana.enabled=false \
  --set prometheus.enabled=false \
  --set promtail.enabled=true
```

**4. Wire Alertmanager → pagemenot**

Pagemenot runs as docker compose on your host; Alertmanager is inside minikube.
`host.minikube.internal` resolves to the host from inside minikube.

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-pagemenot
  namespace: monitoring
stringData:
  alertmanager.yaml: |
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname', 'job']
      group_wait: 10s
      group_interval: 5m
      repeat_interval: 12h
      receiver: pagemenot
    receivers:
      - name: pagemenot
        webhook_configs:
          - url: http://host.minikube.internal:8080/webhooks/alertmanager
            send_resolved: false
EOF

# Patch kube-prom to use this secret
kubectl patch alertmanager kube-prom-kube-prometheus-alertmanager \
  --namespace monitoring \
  --type merge \
  -p '{"spec":{"configSecret":"alertmanager-pagemenot"}}'
```

**5. Port-forward endpoints**

```bash
# Run each in a separate terminal (or use tmux/screen)
kubectl port-forward -n monitoring svc/kube-prom-kube-prometheus-prometheus 9090:9090
kubectl port-forward -n monitoring svc/kube-prom-grafana                    3000:80
kubectl port-forward -n monitoring svc/loki                                  3100:3100
kubectl port-forward -n monitoring svc/kube-prom-kube-prometheus-alertmanager 9093:9093
```

**6. Get Grafana API key**

```bash
# Open http://localhost:3000 — login: admin / pagemenot
# Navigate to: Administration → API Keys → Add API key
# Role: Editor, no expiry
```

**7. Update pagemenot .env**

```env
PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100
GRAFANA_URL=http://localhost:3000
GRAFANA_API_KEY=<paste key from step 6>
```

Restart pagemenot: `docker compose restart pagemenot`

**8. Verify connection**

```bash
/pagemenot status    # in Slack — should show Prometheus, Loki, Grafana as connected
```

**Cleanup (complete teardown)**

```bash
minikube delete          # destroys the entire cluster and all data
# That's it. Nothing persists outside the minikube VM.
```

---

### Path B: Grafana Cloud Free Tier (Zero Infra, No K8s)

Free tier: 10k Prometheus active series, 50GB Loki/month, hosted Grafana, hosted Alertmanager.
No local cluster needed — just point pagemenot at the cloud endpoints.

| What you get | Limit |
|---|---|
| Prometheus (Grafana Mimir) | 10k active series |
| Loki | 50GB/month |
| Grafana | hosted, unlimited dashboards |
| Alertmanager | hosted |

**1. Sign up**

Go to [grafana.com](https://grafana.com) → Start for free → create a stack (choose a region).

**2. Get connection details**

In your Grafana Cloud portal → Connections → Add new connection:

| Setting | Where to find it |
|---|---|
| `PROMETHEUS_URL` | Prometheus → Details → Prometheus endpoint URL (without `/api/prom`) |
| `PROMETHEUS_AUTH_TOKEN` | Prometheus → Details → Password (generate API token) |
| `LOKI_URL` | Loki → Details → Loki endpoint URL |
| `LOKI_AUTH_TOKEN` | Loki → Details → Password |
| `GRAFANA_URL` | Your stack URL, e.g. `https://yourstack.grafana.net` |
| `GRAFANA_API_KEY` | Grafana → Administration → API Keys → Add |

Grafana Cloud Prometheus and Loki use HTTP Basic Auth — username is a numeric ID, password is an API token.
Map these to the Bearer token fields:

```env
PROMETHEUS_URL=https://prometheus-prod-XX-prod-XX-X.grafana.net
PROMETHEUS_AUTH_TOKEN=<api-token>
LOKI_URL=https://logs-prod-XX.grafana.net
LOKI_AUTH_TOKEN=<api-token>
GRAFANA_URL=https://yourstack.grafana.net
GRAFANA_API_KEY=<grafana-api-key>
GRAFANA_ORG_ID=<numeric-org-id>
```

> **Note**: Grafana Cloud uses Basic Auth (`username:password`), not Bearer tokens. The current
> tools.py sends `Authorization: Bearer <token>`. For Grafana Cloud, update `PROMETHEUS_AUTH_TOKEN`
> and `LOKI_AUTH_TOKEN` to base64-encoded `username:token` and set the header format to Basic Auth.
> Track this as a follow-up: [issue: add Basic Auth support for hosted Prometheus/Loki].

**To send your own metrics to Grafana Cloud Prometheus** (optional — so your services appear in pagemenot queries):

```bash
# If you have Prometheus running (e.g., from minikube path above), add remote_write:
helm upgrade kube-prom prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --reuse-values \
  --set prometheus.prometheusSpec.remoteWrite[0].url="https://prometheus-prod-XX.grafana.net/api/prom/push" \
  --set prometheus.prometheusSpec.remoteWrite[0].basicAuth.username="<numeric-user-id>" \
  --set prometheus.prometheusSpec.remoteWrite[0].basicAuth.password.name="grafana-cloud-secret" \
  --set prometheus.prometheusSpec.remoteWrite[0].basicAuth.password.key="password"
```

---

### Comparison

| | Minikube | Grafana Cloud Free |
|---|---|---|
| Cost | Free | Free |
| Setup time | ~15 min | ~5 min |
| Requires K8s | Yes (local) | No |
| Tests kubectl rollback tool | Yes | No |
| Always-on | No (local) | Yes |
| Real alert firing | Yes (Alertmanager) | Yes (hosted Alertmanager) |
| Cleanup | `minikube delete` | Delete stack in UI |

---

## AWS IAM Role Setup

Required when `AWS_ROLE_ARN` is set. Pagemenot assumes this role to query AWS services.

### Create the role

```bash
# Replace ACCOUNT_ID with your AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

sed -i "s/ACCOUNT_ID/$ACCOUNT_ID/" deploy/pagemenot-trust-policy.json

aws iam create-role \
  --role-name pagemenot-exec \
  --assume-role-policy-document file://deploy/pagemenot-trust-policy.json

aws iam put-role-policy \
  --role-name pagemenot-exec \
  --policy-name pagemenot-policy \
  --policy-document file://deploy/pagemenot-iam-policy.json

aws iam get-role --role-name pagemenot-exec \
  --query Role.Arn --output text
```

Paste the output ARN into `.env`:
```
AWS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/pagemenot-exec
```

### Permissions granted (read-only)

| Service | Actions |
|---------|---------|
| ECS | DescribeServices, DescribeTasks, ListTasks, ListServices |
| Auto Scaling | DescribeAutoScalingGroups, DescribeScalingActivities |
| ElastiCache | DescribeCacheClusters, DescribeReplicationGroups |
| CloudWatch | GetMetricStatistics, GetMetricData, ListMetrics, DescribeAlarms |
| CloudWatch Logs | GetLogEvents, FilterLogEvents, DescribeLogGroups |

All actions are read-only. Write actions (UpdateService, SetDesiredCapacity, etc.) are not granted and are blocked in code.

### Scope to specific resources (optional)

Replace `"Resource": "*"` in `pagemenot-iam-policy.json` with specific ARNs:

```json
"Resource": [
  "arn:aws:ecs:us-east-1:ACCOUNT_ID:service/prod-cluster/*",
  "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/prod/*:*"
]
```
