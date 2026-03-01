# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

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
