# Pagemenot — Roadmap

## 🔄 IN PROGRESS — GCP + ECS testing (branch: `feature/gcp-testing`)
> Context ran out mid-session. Resume here.

### State as of 2026-03-09 (session 2)
- App UP at `34.123.60.64:8080/health`, image `c39040d84a11` (AR pull done today)
- `gcp-hello` ingress: `all`, service URL: 200 OK

### Fixes applied this session (NOT YET COMMITTED — local only)
1. `docker-compose.yml`: added `image: us-central1-docker.pkg.dev/zipintel/pagemenot/pagemenot:latest` — fixes `docker compose pull` triggering local build
2. `knowledge/runbooks/cloud-run-unavailable.md`: added `alert: Cloud Run uptime check failing, Cloud Run service unavailable` — fixes RAG ranking (was beating cloud-sql by only 0.005 cosine distance)
3. VM docker-compose.yml patched in-place (same as #1); cloud-run-unavailable.md synced via scp; ChromaDB re-ingested

### GCP alarm test results (updated)
- ✅ Test 3 — GCE nginx stop → auto-resolved 36s (prev session)
- ✅ Test 2 — GCE VM stop → auto-resolved 25s (prev session)
- ✅ **Test 1 — Cloud Run uptime** → CONFIRMED: `service=gcp-hello`, `cloud-run-unavailable.md`, 4 steps OK, auto-resolved 18.9s, postmortem written, no tickets
- ✅ False tickets closed: PD Q1AG205EKSC1O1, Q0X9B1EQECEJEY; Jira PMN-116

### GCS 403 (non-blocking, fix before PR)
`pagemenot-sa` missing write on `pagemenot-state` bucket — dedup not persisted to GCS.
Fix:
```
gcloud storage buckets add-iam-policy-binding gs://pagemenot-state \
  --member=serviceAccount:pagemenot-sa@zipintel.iam.gserviceaccount.com \
  --role=roles/storage.objectAdmin
```

### Next immediate steps
- [ ] Fix GCS 403 (run command above)
- [ ] Commit `docker-compose.yml` + `cloud-run-unavailable.md` fixes
- [ ] **GCP-08: Cloud SQL auto-resolve E2E** (02-02 task 2):
  ```
  # Stop instance
  gcloud sql instances patch pagemenot-test-sql --project=zipintel --activation-policy=NEVER
  # Wait for STOPPED, then POST:
  curl -s -X POST http://34.123.60.64:8080/webhooks/generic -H "Content-Type: application/json" \
    -d '{"incident":{"condition_name":"Cloud SQL instance down","policy_name":"cloud-sql-unavailable","state":"open","summary":"Cloud SQL instance pagemenot-test-sql is unavailable","resource":{"type":"cloudsql_database","labels":{"database_id":"zipintel:pagemenot-test-sql","project_id":"zipintel"}},"resource_display_name":"pagemenot-test-sql"}}'
  ```
  Expected: describe→operations list→restart, auto-resolved, no tickets
- [ ] **Wave 3: approval flow tests** (02-03) — set `PAGEMENOT_APPROVAL_GATE=true` on VM first
- [ ] Uncomment GCP in `setup.sh`
- [ ] Update README — remove "🔜 coming soon" for GCP
- [ ] Create PR `feature/gcp-testing` → `main`

### State as of last session (2026-03-08)
- **Postmortems dir ownership fixed**: `sudo chown -R 1000:1000 ~/pagemenot/knowledge/postmortems` on VM

### Fixes applied this session (all in latest image)
1. `triage.py`: Clear dedup on auto-resolve (`_clear_dedup` called after `resolved_automatically=True`)
2. `triage.py`: Substitute `{{ service }}` in Slack exec display (not just at exec time)
3. `tools.py`: Strip gcloud SSH metadata noise from exec output (`_GCLOUD_SSH_NOISE` regex, module-level)
4. `triage.py`: `uptime_url` resource type handler — extracts Cloud Run service from host label using two regex patterns (with/without revision ID), Gemini-reviewed
5. `triage.py` + `tools.py`: All fixes Gemini-reviewed before applying

### GCP alarm test results
- ✅ Test 3 — nginx stop → auto-resolved 36s, postmortem written, no tickets
- ✅ Test 2 — VM stop → auto-resolved 25s (`gce-instance-stopped.md`), postmortem written
- ❌ Test 1 — Cloud Run uptime check → `service=unknown` → exec failed → false PD+Jira created (PMN-116, Q1AG205EKSC1O1)
  - Fix is in `cb-build8` (`uptime_url` handler) — **needs re-test next session**
- ⚠️  False tickets to close manually: PD `Q1AG205EKSC1O1`, Jira `PMN-116`

### Next immediate steps
- [ ] **Re-test Cloud Run** (Test 1) with new image:
  ```
  gcloud run services update gcp-hello --ingress=internal --region=us-central1 --project=zipintel
  ```
  Expect: `service=gcp-hello` extracted, exec succeeds, no tickets
- [ ] **Close false tickets**: resolve PD `Q1AG205EKSC1O1`, close Jira `PMN-116`
- [ ] **Test ECS — auto-fix scenario** (no human):
  `python scripts/simulate_incident.py checkout-oom` on EC2 (`54.73.77.66`)
  Expect: kubectl rollout undo, auto-resolved, postmortem, no tickets
- [ ] **Test ECS — approval button scenario**:
  `python scripts/simulate_incident.py payment-500s` on EC2
  Expect: Slack approval button, human approves, exec runs, Jira+PD created (high severity)
- [ ] Audit ECS runbook exec steps for correctness (same pattern as Cloud Run fix)
- [ ] **Uncomment GCP in `setup.sh`**
- [ ] **Update README** — remove "🔜 coming soon" for GCP
- [ ] **Create PR** `feature/gcp-testing` → `main` once all tests pass

### What was fixed this session
- `main.py`: NR webhook filter — `current_state`/`state` normalization (Gemini buddy-checked)
- `Dockerfile`: added `openssh-client` to gcp stage (needed for `gcloud compute ssh` inside container)
- `gce-nginx-stopped.md`: added `--tunnel-through-iap` to all ssh exec steps
- VM resized: e2-micro → e2-small (was OOM-killing sshd)
- AR IAM: `pagemenot-sa` granted `roles/artifactregistry.reader`
- NR: infra agent on `gcp-app-vm`, policy `1674907`, channel `515657` → `http://34.123.60.64:8080/webhooks/newrelic`
- **NEVER build Docker on pagemenot VM** — always pull from AR

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
