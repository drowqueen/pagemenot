# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

### Added
- **Runbook templating** — exec steps support `{{ service }}` placeholder; substituted at runtime with the service name extracted from the alert. Runbooks no longer need hardcoded resource names.
- **GCP resource label map** — service name extraction for GCP alerts now uses `resource.labels` per resource type instead of a heuristic. Covers: `cloudsql_database` (`instance_id`), `spanner_instance` (`instance_id`), `pubsub_subscription` (`subscription_id`), `pubsub_topic` (`topic_id`), `k8s_cluster` (`cluster_name`), `k8s_node` (`node_name`), `k8s_pod` (`pod_name`), `cloud_function` / `cloudfunctions_function` (`function_name`), `gcs_bucket` (`bucket_name`), `redis_instance` (`instance_id`), `dataflow_job` (`job_name`), `gae_app` (`project_id`), `gae_service` (`module_id`), `cloud_tasks_queue` (`queue_id`). Falls back to `resource_display_name` → `service_name` label → heuristic.
- **Azure Monitor support** — webhook parser, cloud provider detection, exec routing for Azure CLI commands
- **Azure runbooks** — App Service, Cosmos DB (throttled + unavailable), Function App, PostgreSQL Flexible Server, Redis Cache, SQL Database, VM (stopped + nginx down)

### Fixed
- All Azure runbooks replaced hardcoded resource names with `{{ service }}` — works for any instance of a given service type
- GCP uptime check (`uptime_url`) service extraction — now parses Cloud Run service name from host URL before falling back to heuristic
- Azure PostgreSQL Flexible Server approval flow — `wait --timeout 300` exiting non-zero on slow cold-starts caused false escalation; timeout raised to 600s, wait + verify steps changed from `exec:approve:` to `exec:` (auto after start approval)
- Approval state GCS write failures silently swallowed at WARNING level — now logged at ERROR
- `handle_approve` receipt not logged — added `INFO` entry log with approval ID and user for tracing

### Changed
- `ThreadPoolExecutor` max_workers 3 → 6 — prevents executor starvation when long-running `az wait` steps (up to 600s) consume threads concurrently with triage crew runs
- `pagemenot_az_timeout` 360s → 660s — subprocess timeout now exceeds maximum `az wait --timeout 600` duration

---

## [0.1.0] — 2026-02-26

### Added
- **Core** — CrewAI 3-agent crew (MonitorAgent → DiagnoserAgent → RemediatorAgent) with hierarchical supervisor
- **RAG** — ChromaDB PersistentClient (embedded, no external service) over runbooks and postmortems
- **Slack** — Bolt Socket Mode integration: `/pagemenot triage`, `@pagemenot` mentions, passive channel monitoring
- **Webhooks** — FastAPI receivers for PagerDuty, OpsGenie, Datadog, New Relic, Grafana, Alertmanager, generic
- **Integrations** — Prometheus, Grafana, Loki, Datadog, New Relic, PagerDuty, OpsGenie, GitHub, Kubernetes
- **Multi-cloud auth** — Bearer token support for Prometheus and Loki; `X-Grafana-Org-Id` / `X-Scope-OrgID` for Grafana Cloud / multi-tenant Loki
- **Mock layer** — Auto-activates per integration when real credentials are absent; transparent to agents
- **Trigger modes** — Each Slack trigger independently togglable via `PAGEMENOT_ENABLE_*` env vars
- **Incident simulator** — `scripts/simulate_incident.py` with 5 scenarios and `--source` flag for any webhook format
- **Docker** — Single-container deployment (no postgres, no external ChromaDB); `chromadata` volume for persistence
- **Git hooks** — `pre-commit` (blocks credentials, `.env`, large/binary files) + `pre-push` (blocks direct pushes to main)
- **Deployment docs** — `docs/deployment.md` covering AWS t3.micro, GCP e2-micro, Hetzner, DigitalOcean, bare metal

### Fixed
- `ingest_all()` was never called at startup — wired into FastAPI lifespan
- ChromaDB `HttpClient` replaced with `PersistentClient` (no separate server needed)
- Hardcoded `/app/` paths in `rag.py` — replaced with `_REPO_ROOT` + `KNOWLEDGE_DIR` env override
- `asyncio.get_event_loop()` deprecated in Python 3.10+ — replaced with `get_running_loop()`
- Dockerfile referenced `sentinel/` and `sentinel.main` — fixed to `pagemenot/`
- Removed unused postgres service from `docker-compose.yml`
