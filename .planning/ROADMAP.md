# Roadmap: Pagemenot

**Milestone 1: GCP Support**

## Phase 1: RAG Cloud Provider Filtering

**Goal:** Fix cross-cloud runbook contamination so RAG returns only runbooks matching the incident's cloud provider.
**Requirements:** BUG-01

### Plans
1. Add cloud provider metadata to RAG — tag each runbook/postmortem with its cloud provider during ingest, filter ChromaDB queries by provider at retrieval time

### Success Criteria
1. `search_runbooks("nginx stopped", provider="gcp")` returns only GCP runbooks, zero AWS results
2. `search_runbooks("ecs service crash", provider="aws")` returns only AWS runbooks, zero GCP results
3. Existing AWS alert triage still matches AWS runbooks (no regression)

---

## Phase 2: GCP Alert Ingestion + Exec

**Goal:** Parse GCP-sourced alerts from Cloud Monitoring, New Relic, and Grafana; execute gcloud-based runbook steps from the container; auto-resolve Cloud Run and Cloud SQL incidents; validate approval flow for all service types.
**Requirements:** GCP-01, GCP-02, GCP-03, GCP-04, GCP-05, GCP-06 (deferred — test VM deleted), GCP-07, GCP-08, GCP-09, GCP-10

### What's already done
- GCE nginx stopped: Cloud Monitoring alert → auto-resolve → Slack summary ✓ (battle tested)

### Plans
1. ~~GCP alert parsing — fix `cloud_provider` detection for New Relic infra (GCP VM) and Grafana alerts; Cloud SQL runbook with `<!-- exec: -->` steps~~ **Complete (2026-03-09)**
2. ~~GCP exec verification — validate Cloud Run ingress restore and Cloud SQL instance restart exec steps; confirm auto-resolve end-to-end for both~~ **Complete (2026-03-11)**
3. ~~Approval flow — test all three service types (GCE nginx, Cloud Run, Cloud SQL) with approval button; confirm exec runs only after approve click~~ **Complete (2026-03-11)**
4. ~~AWS ECS + multicloud — stand up ECS cluster (EC2 t2.micro), test reject/approve gate for ECS, fire simultaneous AWS+GCP alerts to validate multicloud independence~~ **Complete (2026-03-11)**

### Success Criteria
1. New Relic infra alert for gcp-app-vm routes through `/webhooks/newrelic` and sets `cloud_provider="gcp"`
2. Grafana alert for a GCP target routes through `/webhooks/grafana` and sets `cloud_provider="gcp"`
3. Cloud Run unavailable: alert fires → pagemenot restores ingress automatically → Slack auto-resolved summary (no human action)
4. Cloud SQL unavailable: alert fires → pagemenot restarts instance automatically → Slack auto-resolved summary (no human action)
5. GCE nginx: approval button triggers nginx restart, Slack confirms exec outcome
6. Cloud Run: approval button triggers ingress restore, Slack confirms exec outcome
7. Cloud SQL: approval button triggers instance restart, Slack confirms exec outcome
8. ECS reject gate: task stopped → alarm → Slack shows Approve/Reject → Reject → no exec ran
9. ECS approve gate: same path → Approve → force-new-deployment runs → task recovers
10. Multicloud: ECS + Cloud Run alarms fired simultaneously → two independent Slack threads, no cross-contamination

---

## Phase 3: End-to-End Tests + Ship

**Goal:** Four alarm scenarios pass end-to-end (alert fires, pagemenot resolves, Slack summary posted), then merge to main.
**Requirements:** E2E-01, E2E-02, E2E-03, E2E-04, SHIP-01, SHIP-02

### Plans
1. Run all four alarm tests — trigger each alarm condition (nginx stopped, VM stopped, Cloud Run unavailable, Grafana GCP alert), confirm pagemenot auto-resolves and posts Slack summary without paging
2. Ship — update README GCP section, open PR from `feature/gcp-testing` to `main`, merge

### Success Criteria
1. GCE nginx stopped: alarm fires, pagemenot restarts nginx, Slack thread shows auto-resolved summary, no PagerDuty page
2. GCE VM stopped: alarm fires, pagemenot starts VM, Slack thread shows auto-resolved summary
3. Cloud Run unavailable: alarm fires, pagemenot restores ingress, Slack thread shows auto-resolved summary
4. Grafana GCP alert: alert received, routed, handled correctly in Slack
5. README no longer says "coming soon" for GCP
6. `feature/gcp-testing` PR merged to `main`

---

## Phase 4: Azure Monitor Support and Testing

**Goal:** Add Azure Monitor alert ingestion, az CLI exec, runbooks for VM and App Service, and end-to-end testing against real Azure free-tier resources. One pagemenot instance (GCP VM) handles all three clouds.
**Requirements:** AZ-01, AZ-02, AZ-03, AZ-04, AZ-05, AZ-06, AZ-07, AZ-08 (sub: webhook returns 200 for Fired — covered by AZ-01), AZ-09 (sub: webhook skips Resolved — covered by AZ-02)
**Depends on:** Phase 3
**Plans:** 6/6 plans complete

Plans:
- [ ] 04-01-PLAN.md — Azure test scaffold (TDD: failing tests for all AZ requirements)
- [ ] 04-02-PLAN.md — triage parse branch, /webhooks/azure endpoint, az login, runbooks, cloudbuild target=cloud
- [ ] 04-03-PLAN.md — Cloud Build + VM deploy + /webhooks/azure smoke test
- [ ] 04-04-PLAN.md — Real Azure E2E: B1s VM alert → pagemenot → az vm start → recovery
- [ ] 04-05-PLAN.md — Final gate + PR to main

### Success Criteria
1. `_parse_alert("azure", firing_payload)` returns cloud_provider=["azure"], correct title/service/severity
2. Sev0→critical, Sev1→high, Sev2→medium, Sev3→low, Sev4→low
3. POST /webhooks/azure Fired → {"status":"accepted"}; Resolved → {"status":"skipped"}
4. `az` exec commands route through exec_shell (no new routing)
5. Real Azure Monitor alert reaches pagemenot and triggers Slack triage thread
6. Approve path: az vm start runs, VM recovers; Reject path: no exec runs
7. `pytest tests/ -x -q` exits 0

---

*Created: 2026-03-08*
