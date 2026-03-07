# Codebase Conventions

## Language and Runtime

- Python 3.12+, enforced via `pyproject.toml` (`requires-python = ">=3.12"`)
- `ruff` linter, line-length 100, target `py312`
- All config via Pydantic Settings / `.env` — never hardcode values

---

## File and Module Layout

```
pagemenot/          # package root
  config.py         # Settings singleton, imported everywhere as `settings`
  crew.py           # CrewAI crew factory
  main.py           # FastAPI app + lifespan + webhook handlers
  mock_tools.py     # Mock integration layer
  slack_bot.py      # Slack Bolt async app
  tools.py          # Real CrewAI tool implementations
  triage.py         # Core triage logic (dataclass, pure helpers, async runner)
  rag.py            # ChromaDB ingestion and retrieval
```

Module-level loggers are created per-module:

```python
logger = logging.getLogger("pagemenot.triage")
```

---

## Configuration Pattern

Single `Settings` class in `config.py` using `pydantic_settings.BaseSettings`.
Instantiated once at module level as `settings = Settings()`.
All other modules import `from pagemenot.config import settings`.

```python
class Settings(BaseSettings):
    slack_bot_token: str                          # required — no default
    llm_model: str = "gpt-4o"                    # optional — has default
    prometheus_url: Optional[str] = None          # optional integration
    pagemenot_dedup_ttl_short: int = 600          # tunable via env

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
```

Computed properties on `Settings` summarize derived state:

```python
@property
def enabled_integrations(self) -> list[str]:
    ...
```

---

## Type Annotations

All functions and methods are fully type-annotated. Python 3.10+ union syntax (`X | Y`) is used throughout:

```python
async def pop(self, key: str) -> dict | None:
async def _check_sig(secret: Optional[str], sig_header: Optional[str]) -> None:
def _chunk_document(text: str, max_chars: int = 1500) -> list[str]:
```

`dataclass` with `field(default_factory=...)` for mutable defaults:

```python
@dataclass
class TriageResult:
    alert_title: str
    service: str
    severity: str
    evidence: list[str] = field(default_factory=list)
    execution_log: list[str] = field(default_factory=list)
    suppressed: bool = False
    duration_seconds: float = 0.0
```

`TYPE_CHECKING` guard used to avoid circular imports for type-only references:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pagemenot.triage import TriageResult
```

---

## Async Patterns

The application is async-first (FastAPI + Slack Bolt async).

**CPU/blocking work runs in a thread pool** — never `await` blocking calls directly:

```python
_executor = ThreadPoolExecutor(max_workers=3)

loop = asyncio.get_running_loop()
raw = await loop.run_in_executor(_executor, _run_crew_sync, summary)
```

**Fire-and-forget tasks** use `asyncio.create_task()` for background work that should not block the caller:

```python
asyncio.create_task(
    _do_triage(say, source="manual", payload={"text": text})
)
asyncio.create_task(_resolve_jira_ticket(jira_url))
```

**`asyncio.gather()`** for parallel independent async calls:

```python
jira_url, pd_url = await asyncio.gather(*tasks, return_exceptions=True)
```

**`asyncio.sleep()` for delay timers** (auto-approve), cancellable via `CancelledError`:

```python
try:
    await asyncio.sleep(settings.pagemenot_autoapprove_delay)
except asyncio.CancelledError:
    return
finally:
    _pending_autoapprove.pop(task_id, None)
```

**`@asynccontextmanager`** for FastAPI lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown
```

---

## Error Handling Patterns

**Fail-safe / non-fatal exceptions are caught and logged, not re-raised:**

```python
try:
    os.makedirs(settings.chroma_path, exist_ok=True)
    ...
except Exception as e:
    logger.warning(f"Knowledge ingestion failed (non-fatal): {e}")
    logger.info("Pagemenot works without knowledge — it learns as you use it.")
```

**HTTP errors raise FastAPI `HTTPException`:**

```python
if not _verify_hmac(...):
    raise HTTPException(status_code=401, detail="Invalid signature")
```

**Return value checks instead of exceptions** where callers must handle both outcomes:

```python
jira_url, pd_url = await asyncio.gather(*tasks, return_exceptions=True)
if isinstance(jira_url, str):
    ...
```

**`except Exception` with specific log context** in Slack handlers — bad payloads are logged and dropped, never bubble up to the user as a 500:

```python
except Exception as e:
    logger.error(f"Triage failed: {e}", exc_info=True)
    await say(f"Triage failed: {str(e)[:200]}. Check logs for details.")
```

---

## Naming Conventions

| Pattern | Convention |
|---------|------------|
| Module-private helpers | `_function_name` prefix |
| Module-level singletons | `_var_name` (e.g. `_app`, `_client`, `_executor`) |
| Public API functions | `snake_case` no prefix |
| Config keys (env vars) | `SCREAMING_SNAKE_CASE` in env, `snake_case` on `Settings` |
| Dataclasses | `PascalCase` |
| Thread locks | `_noun_lock` (e.g. `_dedup_lock`, `_scenarios_lock`) |
| Dicts tracking state | `_active_noun` (e.g. `_active_incidents`, `_active_jira_tickets`) |

Private functions that implement public interfaces use double-underscore prefix only where disambiguation is needed; single underscore is the default.

---

## Deduplication Pattern

Thread-safe in-memory dict keyed by `(service, title_hash)` tuple with monotonic expiry:

```python
_active_incidents: dict[tuple[str, str], float] = {}
_dedup_lock = threading.Lock()

def _check_and_register(service: str, title: str, severity: str) -> bool:
    key = _dedup_key(service, title)
    now = time.monotonic()
    with _dedup_lock:
        expired = [k for k, exp in _active_incidents.items() if now > exp]
        for k in expired:
            del _active_incidents[k]
        if key in _active_incidents:
            return True
        _active_incidents[key] = now + ttl
        return False
```

---

## Lazy Import Pattern

To avoid circular imports and expensive startup costs, some modules are imported inside functions:

```python
def _run_crew_sync(alert_summary: str) -> str:
    from pagemenot.crew import build_triage_crew
    ...

def _seed_mock_if_needed(parsed_alert: dict):
    from pagemenot.mock_tools import seed_mock_context
    ...
```

---

## Input Validation / Security

Credential redaction before passing any text to LLMs:

```python
_REDACT_CREDENTIAL_RE = re.compile(
    r"((?:password|passwd|secret|token|api.?key|...)"\
    r'\s*[:=]\s*)[^\s,\'";&\n]{2,}',
    re.IGNORECASE,
)

def _redact_sensitive(text: str) -> str:
    text = _REDACT_CREDENTIAL_RE.sub(r"\1[REDACTED]", text)
    text = _REDACT_DSN_RE.sub("[DSN_REDACTED]", text)
    text = _REDACT_IPV4_RE.sub("[IP_REDACTED]", text)
    return text
```

Shell command safety — service/name parameters validated against an allowlist regex before use in subprocess calls:

```python
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")

def _safe_name(name: str) -> str:
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"Unsafe characters in name: {name!r}")
    return name
```

HMAC webhook verification uses `hmac.compare_digest` (constant-time):

```python
expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
return hmac.compare_digest(expected, sig)
```

---

## Tool Registration Pattern (CrewAI)

Real tools use `@tool` decorator from `crewai.tools`. Auto-detection selects real vs. mock at startup:

```python
def _pick(condition, real, mock, label):
    if condition:
        logger.info(f"✅ {label}: LIVE")
        return real
    logger.info(f"🔶 {label}: MOCK")
    return mock

monitor_tools = [
    _pick(settings.prometheus_url, query_prometheus, mock_prometheus, "Prometheus"),
    ...
]
```

---

## Runbook Format Conventions

Runbooks live in `knowledge/runbooks/*.md`. Executable steps are tagged with HTML comments:

```markdown
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
```

- `<!-- exec: cmd -->` — runs automatically (dry-run aware)
- `<!-- exec:approve: cmd -->` — queued for human approval when `PAGEMENOT_APPROVAL_GATE=true`
- `{{ service }}` and `{{ namespace }}` are template variables resolved at execution time

Runbook frontmatter fields (plain key-value, not YAML):

```markdown
service: general
date: 2026-01-01
```

---

## Postmortem Format Conventions

Postmortems live in `knowledge/postmortems/*.md`. Auto-generated ones follow:

```markdown
# Postmortem: <alert_title>

service: <service>
date: <YYYY-MM-DD>
root_cause: <one line>
resolution: <Human-approved runbook execution | Auto-resolved by runbook execution>

## Alert
## Root Cause
## Execution Log
## Resolved By
## Jira          (optional)
```

Filename pattern for auto-generated: `<service>_<YYYYMMDD-HHMMSS>-<6-char uuid hex>.md`

Human-authored postmortems follow the same `# Title`, frontmatter fields, and `## Section` structure but may include `## Timeline`, `## Action Items`, etc.
