# Pagemenot — Roadmap

## 🔄 IN PROGRESS — GCP testing (branch: `feature/gcp-testing`)
> Context ran out mid-session. Resume here.

### Next immediate steps (in order)
- [ ] **Verify build** — check VM `/tmp/build3.log`; confirm `pagemenot` container is up at `34.123.60.64:8080`
  - `gcloud compute ssh pagemenot --zone=us-central1-a --project=zipintel --command='tail -10 /tmp/build3.log; docker ps'`
  - If build failed again, check `EXIT` line in log for new error
- [ ] **Uncomment GCP in `setup.sh`** — remove `# GCP and Azure support coming soon` comment block, uncomment the GCP credential prompts and menu option 3
- [ ] **Update README** — remove "🔜 coming soon" for GCP; GCP is now supported and tested
- [ ] **Create PR** `feature/gcp-testing` → `main` once tests pass

### GCP test scenarios (run after container is up)
- [ ] **Test 1 — Cloud Run unavailable**: `gcloud run services update gcp-hello --ingress=internal --region=us-central1 --project=zipintel` → wait for Cloud Monitoring alert → pagemenot should auto-fix with `--ingress=all`
- [ ] **Test 2 — GCE VM stopped**: `gcloud compute instances stop gcp-app-vm --zone=us-central1-a --project=zipintel` → wait for uptime check alert → pagemenot should auto-start
- [ ] **Test 3 — GCE nginx stopped**: `gcloud compute ssh gcp-app-vm --zone=us-central1-a --project=zipintel --command="sudo systemctl stop nginx"` → wait for HTTP uptime alert → pagemenot should auto-restart
- [ ] **Test 4 — Grafana Cloud alert**: Grafana Infinity rule fires when `gcp-app-vm:80` is unreachable → routes to pagemenot `/webhooks/grafana`

### GCP infra state (do NOT delete until tests pass)
| Resource | Type | Details |
|----------|------|---------|
| `pagemenot` | GCE e2-micro | 34.123.60.64, us-central1-a — pagemenot app VM, keep running |
| `gcp-app-vm` | GCE e2-micro | 34.172.81.177, us-central1-a — test target, nginx on port 80 |
| `gcp-hello` | Cloud Run | us-central1, stable tag = `gcp-hello-00001-779` |
| `pagemenot-sa` | IAM SA | `pagemenot-sa@zipintel.iam.gserviceaccount.com`, attached to pagemenot VM |
| Uptime checks | Cloud Monitoring | `gcp-hello-uptime`, `gcp-app-vm-uptime` |
| Alert policies | Cloud Monitoring | Cloud Run unavailable, GCE stopped, GCE nginx down |
| Contact point | Grafana Cloud | `pagemenot` → `http://34.123.60.64:8080/webhooks/grafana` |
| Alert rule | Grafana Cloud | `GCE gcp-app-vm nginx service down`, folder `pagemenot-tests` |

### What was fixed in this session
- `triage.py`: GCP Cloud Monitoring webhook parser (cloud_run_revision, gce_instance, uptime_url)
- `main.py`: skip `state=closed` GCP incidents at `/webhooks/generic`
- `Dockerfile`: `USER root` before apt-get + `USER appuser` after in all CLI stages (aws, gcp, azure, cloud) — was causing `Permission denied` on build
- Runbooks added: `cloud-run-unavailable.md`, `gce-instance-stopped.md`, `gce-nginx-stopped.md` (all exec steps verified)
- Grafana SA token updated in `.env` (see local `.env`, `GRAFANA_API_KEY`)

### Known: AWS stages untested with new USER fix
The `aws` Dockerfile stage had the same bug. AWS tests used `base` target, not `aws`. The fix is in place but `aws` stage hasn't been built since the fix — verify if doing future AWS CLI rebuild.



## Incident lifecycle
- [ ] Dedicated war room Slack channel per incident (auto-created on escalation, archived on resolve)
- [ ] On-call rotation / role assignment in incident thread (IC, Comms Lead, Scribe)
- [ ] Maintenance window suppression (suppress alerts during planned downtime)
- [ ] Escalation timeout — page on-call if incident not resolved in N minutes (configurable)

## Observability
- [ ] Status page integration (Statuspage.io, Better Uptime, incident.io)
- [ ] MTTR / MTTA reporting dashboard (per-service, per-severity)
- [ ] Incident volume trends and common root cause analytics

## Notifications
- [ ] Slack channel per service/team routing (route alerts to the right team channel)
- [ ] Email notification fallback when PD not configured (SMTP optional)

## Approval & execution
- [ ] Cross-instance dedup lock via Redis (prevents duplicate Jira/PD on multi-instance deploy)
- [ ] Approval audit log (who approved what, when, outcome)
- [ ] Persist pending CW verification tasks (survive container restart) — currently in-memory only; SNS OK still closes Jira/PD but Slack thread confirmation is lost if container restarts during verification window

## Cloud exec hardening
- [ ] Audit `exec_kubectl` for unhandled failure modes (same treatment as exec_aws)
- [ ] Audit all exec_* functions with same Gemini review pattern used for exec_aws

## SSM exec support (Linux process diagnostics on EC2)
- [ ] `exec_ssm(instance_id, command)` in tools.py — `ssm:SendCommand` + poll `ssm:GetCommandInvocation` until terminal status
- [ ] `<!-- exec:ssm: ps aux --sort=-%cpu | head -20 -->` tag type in runbooks — routes to `exec_ssm` via `dispatch_exec_step`
- [ ] `AmazonSSMManagedInstanceCore` policy on `pagemenot-exec` IAM role
- [ ] `ec2-high-cpu.md` SSM steps: `ps aux`, `top -bn1`, `systemctl list-units --failed`
- [ ] `ec2-high-cpu.md` approval-gated: `systemctl restart {{ process }}` via SSM
- [ ] SSM agent required on target instances (pre-installed on Amazon Linux 2/2023)

## GCP support (gcloud-only users)
- [ ] `/webhooks/gcp` endpoint — parse Cloud Monitoring incident JSON (`incident.resource_name` → service, `incident.state` open/closed)
- [ ] `exec_gcp_cli(cmd)` in tools.py — subprocess `gcloud ... --format=json`, timeout, stderr as RuntimeError
- [ ] Route `gcloud ` prefix in `dispatch_exec_step`
- [ ] `_parse_alert` source `"gcp"` in triage.py
- [ ] `WEBHOOK_SECRET_GCP` in config + `.env.example`
- [ ] Runbooks: `gce-high-cpu.md`, `cloud-run-errors.md`, `gke-workload-error.md`
- [ ] Service = `incident.resource_name`; use `--ids` or full resource path in exec tags

## Azure support (az-only users)
- [ ] `/webhooks/azure` endpoint — parse Azure Monitor common alert schema (`affectedConfigurationItems[0]` ARM ID → service, `monitorCondition` Fired/Resolved)
- [ ] `exec_azure_cli(cmd)` in tools.py — subprocess `az ... --output json`, timeout, stderr as RuntimeError
- [ ] Route `az ` prefix in `dispatch_exec_step`
- [ ] `_parse_alert` source `"azure"` in triage.py
- [ ] `WEBHOOK_SECRET_AZURE` in config + `.env.example`
- [ ] Service = full ARM resource ID; exec tags use `az ... --ids {{ service }}`
- [ ] Severity map: Sev0→critical, Sev1→high, Sev2→medium, Sev3/4→low
- [ ] Runbooks: `azure-vm-unhealthy.md`, `aks-service-unhealthy.md`, `azure-app-service-errors.md`

## EKS / serverless deploy support
- [ ] Document EKS deployment (IRSA service account annotation, no AWS_ROLE_ARN needed)
- [ ] Document ECS Fargate deployment (task role, no AWS_ROLE_ARN needed)
- [ ] Document Lambda / serverless deployment (execution role, boto3 default chain)
- [ ] Validate kubeconfig handling when running inside cluster (in-cluster config)

## Severity
- [ ] Fine-tune Datadog/NewRelic severity mapping (currently coarse for edge cases)
- [ ] Customer-defined severity override rules (e.g. checkout-service error_rate > 10% → critical)
