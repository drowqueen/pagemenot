# Requirements: Pagemenot

**Defined:** 2026-03-08
**Core Value:** Alert fires → pagemenot resolves it autonomously or hands off with full context already done.

## v1 Requirements (Current Milestone: GCP Support)

### Bug Fix

- [x] **BUG-01**: RAG retrieves only runbooks matching the incident's cloud provider (no cross-cloud contamination)

### GCP — Alert Ingestion

- [x] **GCP-01**: Cloud Monitoring alert payload parsed into normalized triage fields (service, severity, alert_title, resource)
- [x] **GCP-02**: New Relic infra agent alerts for GCP instances routed and parsed correctly
- [x] **GCP-03**: Grafana Cloud alerts for GCP targets routed to `/webhooks/grafana` and handled

### GCP — Exec

- [x] **GCP-04**: pagemenot container can run `gcloud compute ssh` to a GCE VM — done
- [x] **GCP-05**: `gce-nginx-stopped.md` exec steps auto-restart nginx on gcp-app-vm — battle tested ✓
- [ ] **GCP-06**: `gce-instance-stopped.md` exec steps auto-start a stopped GCE VM — deferred: gcp-app-vm deleted before testing; no test target available
- [x] **GCP-07**: `cloud-run-unavailable.md` exec steps restore Cloud Run ingress (auto-resolve, no human action)
- [x] **GCP-08**: `cloud-sql-unavailable.md` runbook + exec steps restart a stopped Cloud SQL instance (auto-resolve, no human action)

### GCP — Approval Flow

- [x] **GCP-09**: Approval button flow tested for GCE nginx, Cloud Run, and Cloud SQL — exec runs only after human approve
- [x] **GCP-10**: Rejected approval posts "Rejected — no action taken" to Slack thread

### AWS — ECS Exec

- [x] **AWS-ECS-01**: ECS reject gate — Reject button posts "Rejected — no action taken", no exec runs
- [x] **AWS-ECS-02**: ECS approve gate — Approve button triggers force-new-deployment, task recovers

### Multicloud

- [x] **MULTI-01**: Simultaneous AWS + GCP alerts handled in independent Slack threads with no cross-contamination

### GCP — End-to-End Tests

- [ ] **E2E-01**: GCE nginx stopped → alert fires → pagemenot auto-resolves → Slack summary posted (no page)
- [ ] **E2E-02**: GCE VM stopped → alert fires → pagemenot auto-resolves → Slack summary posted
- [ ] **E2E-03**: Cloud Run unavailable → alert fires → pagemenot auto-resolves → Slack summary posted
- [ ] **E2E-04**: Grafana alert for GCP target → routed to pagemenot → handled correctly

### GCP — Shipping

- [ ] **SHIP-01**: README updated — GCP no longer marked "coming soon"
- [ ] **SHIP-02**: `feature/gcp-testing` PR reviewed and merged to `main`

## v2 Requirements (Next Milestone: Azure)

### Azure — Alert Ingestion

- **AZ-01**: Azure Monitor alert payload parsed into normalized triage fields
- **AZ-02**: Azure alert severity mapped to pagemenot severity levels

### Azure — Exec

- **AZ-03**: pagemenot container can run `az` CLI commands against Azure resources
- **AZ-04**: Azure runbooks with `<!-- exec: az ... -->` steps verified

### Azure — End-to-End

- **AZ-05**: At least 2 Azure alarm types auto-resolved end-to-end

## Backlog (No Committed Milestone)

### Operations

- **OPS-01**: Escalation timeout — auto-page oncall if incident unresolved in N minutes (configurable)
- **OPS-02**: Per-team Slack channel routing (route alerts to team-specific channels)

### Exec Hardening

- **EXEC-01**: SSM exec for EC2 — `exec_ssm(instance_id, cmd)` via SSM SendCommand + poll
- **EXEC-02**: `ec2-high-cpu.md` runbook with SSM diagnostic + approval-gated restart steps
- **EXEC-03**: Audit `exec_kubectl` for unhandled failure modes
- **EXEC-04**: Audit all `exec_*` functions with same Gemini review pattern used for `exec_aws`

### Reliability

- **REL-01**: Cross-instance dedup lock via Redis (prevents duplicate Jira/PD on multi-replica)
- **REL-02**: Approval audit log (who approved, when, outcome — persisted)
- **REL-03**: Persist pending CW verification tasks across container restarts

## Out of Scope

| Feature | Reason |
|---------|--------|
| War room Slack channel creation | Not needed |
| Status page integration | Not planned |
| MTTR / MTTA dashboard | Not planned |
| Any HTTP dashboard UI | Not planned |
| Kubernetes support | Already done |

## Traceability

| Requirement | Phase | Phase Name | Status |
|-------------|-------|------------|--------|
| BUG-01 | 1 | RAG Cloud Provider Filtering | Complete |
| GCP-01 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-02 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-03 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-04 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-05 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-06 | 2 | GCP Alert Ingestion + Exec | Deferred |
| GCP-07 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-08 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-09 | 2 | GCP Alert Ingestion + Exec | Complete |
| GCP-10 | 2 | GCP Alert Ingestion + Exec | Complete |
| AWS-ECS-01 | 2 | GCP Alert Ingestion + Exec | Complete |
| AWS-ECS-02 | 2 | GCP Alert Ingestion + Exec | Complete |
| MULTI-01 | 2 | GCP Alert Ingestion + Exec | Complete |
| E2E-01 | 3 | End-to-End Tests + Ship | Pending |
| E2E-02 | 3 | End-to-End Tests + Ship | Pending |
| E2E-03 | 3 | End-to-End Tests + Ship | Pending |
| E2E-04 | 3 | End-to-End Tests + Ship | Pending |
| SHIP-01 | 3 | End-to-End Tests + Ship | Pending |
| SHIP-02 | 3 | End-to-End Tests + Ship | Pending |

**Coverage:**
- v1 requirements: 17 total (14 original + AWS-ECS-01, AWS-ECS-02, MULTI-01)
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-03-08*
*Last updated: 2026-03-11*
