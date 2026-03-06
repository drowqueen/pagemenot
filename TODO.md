# Pagemenot — Roadmap

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
