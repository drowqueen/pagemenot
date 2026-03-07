# Stack

## Language & Runtime

| Item | Value |
|------|-------|
| Language | Python 3.12 |
| Runtime | CPython (`python:3.12-slim` base image) |
| Entry point | `python -m pagemenot.main` |
| Port | 8080 |

## Web Framework

| Package | Version | Role |
|---------|---------|------|
| `fastapi` | >=0.115 | HTTP API, webhook receivers |
| `uvicorn[standard]` | >=0.30 | ASGI server |
| `slowapi` | >=0.1.9 | Per-IP rate limiting on `/webhooks/*` |

Routes defined in `pagemenot/main.py`:
- `GET /health`
- `POST /webhooks/pagerduty`
- `POST /webhooks/pagerduty/resolve`
- `POST /webhooks/grafana`
- `POST /webhooks/alertmanager`
- `POST /webhooks/sns` (AWS CloudWatch)
- `POST /webhooks/opsgenie`
- `POST /webhooks/datadog`
- `POST /webhooks/newrelic`
- `POST /webhooks/generic`
- `POST /webhooks/jira`

## AI / Agent Framework

| Package | Version | Role |
|---------|---------|------|
| `crewai[tools,google-genai,litellm]` | >=0.105 | Multi-agent orchestration |

Three agents defined in `pagemenot/crew.py`:
- `Senior SRE Monitoring Specialist` — metrics and logs
- `Principal Incident Analyst` — root cause correlation
- `SRE Remediation Specialist` — runbook lookup, remediation steps

Sequential process (`Process.sequential`). Max iterations: 10 / 10 / 8.

## LLM Providers

Configured via `LLM_PROVIDER` + model-specific key in `.env`. All routed through CrewAI `LLM`.

| Provider | SDK | Default model |
|----------|-----|---------------|
| OpenAI (default) | `openai>=1.40` | `gpt-4o` |
| Anthropic | `anthropic>=0.34` | configurable (e.g. `claude-sonnet-4-6`) |
| Google Gemini | via `crewai[google-genai]` | e.g. `gemini-2.0-flash` |
| Ollama (self-hosted) | `ollama>=0.4` | e.g. `llama3.1` |

Embeddings (CrewAI memory): OpenAI `text-embedding-3-small`. Disabled for Gemini and Ollama.
Optional Ollama embedding model: `nomic-embed-text` — set via `OLLAMA_EMBEDDING_MODEL`.

External LLM compliance gate: startup aborts unless `LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true` in `.env`.

## Vector Store (RAG)

| Package | Version | Mode |
|---------|---------|------|
| `chromadb` | >=0.5 | Embedded (`PersistentClient`) or remote (`HttpClient`) |

- Embedded path: `/app/data/chroma` (Docker volume `chromadata`)
- Remote: `CHROMA_HOST` + `CHROMA_PORT` env vars
- Collections: `incidents` (postmortems), `runbooks`
- Similarity: cosine (`hnsw:space=cosine`)
- Knowledge ingestion: `pagemenot/rag.py` — runs on startup, re-indexes hourly
- Source directories: `knowledge/postmortems/`, `knowledge/runbooks/` (markdown files)

## Slack Integration

| Package | Version | Role |
|---------|---------|------|
| `slack-bolt` | >=1.20 | App framework, Socket Mode |
| `slack-sdk` | >=3.30 | API client |

Socket Mode (WebSocket, no public URL needed). Handler: `AsyncSocketModeHandler`.
Trigger modes (all toggleable via `.env`): channel monitor, `@mentions`, `/pagemenot` slash command, webhooks.

## Configuration

- `pagemenot/config.py` — `pydantic-settings>=2.0` `BaseSettings` subclass
- Source: `.env` file (UTF-8), environment variables
- All settings namespaced under `PAGEMENOT_*` or integration-specific prefixes

## Approval State Persistence

Three-tier store (priority order):
1. Redis — `redis[asyncio]>=5.0`, no TTL, set via `REDIS_URL`
2. JSON file — `/app/data/approvals.json` (Docker volume `appdata`)
3. In-memory — lost on restart

## HTTP Client

`httpx>=0.27` — all outbound API calls. Timeout: `PAGEMENOT_HTTP_TIMEOUT` (default 10s).

## Build System

| Item | Detail |
|------|--------|
| Build backend | `setuptools>=68` + `wheel` |
| Packaging | `pyproject.toml` (PEP 517) |
| Linter | `ruff>=0.5`, target `py312`, line length 100 |
| Tests | `pytest>=8.0`, `pytest-asyncio>=0.23`, `asyncio_mode=auto` |

## Docker

Multi-stage `Dockerfile`:

| Stage | Contents |
|-------|---------|
| `builder` | pip deps compiled into `/venv`; not shipped |
| `base` | venv + app code + `kubectl` v1.35.2 (sha256 verified, arch-aware) |
| `aws` | `base` + AWS CLI v2 |
| `gcp` | `base` + `google-cloud-cli` |
| `azure` | `base` + `azure-cli` |
| `cloud` | `base` + all three CLIs |

Build target selected by `PAGEMENOT_BUILD_TARGET` env var (default: `base`).

Runtime user: `appuser` (uid 1000). Health check: `curl -f http://localhost:8080/health`.

## Docker Compose

File: `docker-compose.yml`

| Volume | Mount | Purpose |
|--------|-------|---------|
| `appdata` | `/app/data` | approval JSON, misc data |
| `chromadata` | `/app/data/chroma` | ChromaDB SQLite |
| `chromacache` | `/root/.cache/chroma` | embedding cache |
| bind mount (ro) | `/app/knowledge/runbooks` | runbook markdown |
| bind mount (rw) | `/app/knowledge/postmortems` | postmortem markdown (written at runtime) |

Kubeconfig mount commented out by default; `docker-compose.override.yml` (gitignored) activates it for local dev.

## Subprocess Execution

Runbook exec steps shell out via `subprocess` (kubectl, aws, gcloud). Timeout: `PAGEMENOT_SUBPROCESS_TIMEOUT` (default 30s). Controlled by:
- `PAGEMENOT_EXEC_ENABLED` (master switch, default `true`)
- `PAGEMENOT_EXEC_DRY_RUN` (default `true` — simulate only)
- `PAGEMENOT_APPROVAL_GATE` (default `true` — human approval required for `[NEEDS APPROVAL]` steps)
