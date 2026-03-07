# Testing

## Framework and Configuration

- **pytest** 8.0+, **pytest-asyncio** 0.23+
- `asyncio_mode = "auto"` — all `async def` test functions run automatically without `@pytest.mark.asyncio`
- Test root: `tests/`
- Dev dependencies: `pip install -e ".[dev]"` (installs `pytest`, `pytest-asyncio`, `ruff`)

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
]
```

---

## Running Tests

```bash
# From repo root, with venv active
pytest

# Verbose
pytest -v

# Single file
pytest tests/test_triage.py

# Single class or test
pytest tests/test_triage.py::TestDedupKey
pytest tests/test_triage.py::TestDedupKey::test_case_insensitive

# Linting (separate from tests)
ruff check pagemenot/
```

---

## Test Files

| File | Scope |
|------|-------|
| `tests/conftest.py` | Minimal env setup so `Settings` loads without real secrets |
| `tests/test_triage.py` | Unit tests — pure functions in `triage.py` |
| `tests/test_jira_tracking.py` | Integration tests — Jira/PD state tracking, `_handle_resolve` |

---

## `conftest.py` — Environment Bootstrap

Sets the minimum env vars required by `Settings` so imports don't fail:

```python
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("LLM_MODEL", "gpt-4o")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
```

No fixtures are defined in `conftest.py` — shared fixtures are defined per-file.

---

## Test Structure

Tests are organized into classes by the unit under test. Class names follow `TestFunctionName` or `TestConceptName`:

```python
class TestDedupKey:
    def test_deterministic(self): ...
    def test_case_insensitive(self): ...

class TestCheckAndRegister:
    def test_first_call_not_duplicate(self): ...
    def test_expired_entry_not_duplicate(self, monkeypatch): ...

class TestParseAlert:
    def test_alertmanager_title_and_service(self): ...
    def test_unknown_source_does_not_raise(self): ...
```

Async tests are plain `async def` — no decorator needed:

```python
class TestHandleResolve:
    async def test_no_jira_tracked_skips_close(self, mock_slack_client):
        with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock) as mock_close:
            await main_mod._handle_resolve("alertmanager", am_resolve())
            mock_close.assert_not_called()
```

---

## Fixtures

### State-clearing fixtures (`autouse=True`)

Module-level mutable state is reset before and after each test to prevent cross-test pollution:

```python
@pytest.fixture(autouse=True)
def clear_dedup():
    with _dedup_lock:
        _active_incidents.clear()
    yield
    with _dedup_lock:
        _active_incidents.clear()

@pytest.fixture(autouse=True)
def reset_tracking():
    main_mod._active_jira_tickets.clear()
    main_mod._active_pd_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()
    yield
    main_mod._active_jira_tickets.clear()
    main_mod._active_pd_incidents.clear()
    with _dedup_lock:
        _active_incidents.clear()
```

### Shared mock fixtures

```python
@pytest.fixture
def mock_slack_client():
    mock = AsyncMock()
    mock.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
    with patch("pagemenot.slack_bot.get_client", return_value=mock):
        yield mock
```

### Helper methods on test classes

Private helper methods (`_method`) build reusable test inputs inline without a fixture:

```python
class TestParseAlert:
    def _am(self, status="firing", alertname="OOMKilled", ...):
        return {"status": status, "labels": {...}, "annotations": {...}}

class TestEscalationGate:
    def _make(self, severity, steps=None, approval=None):
        return TriageResult(alert_title="Test Alert", ...)

    def _gate(self, r):
        # pure logic extracted for testing without Slack/crew dependencies
        can_resolve = bool(r.remediation_steps) and not bool(r.needs_approval)
        needs_page = r.severity in ("critical", "high") and not can_resolve
        return can_resolve, needs_page
```

---

## Mocking Approach

### `unittest.mock` — standard library only, no third-party mock libraries

```python
from unittest.mock import AsyncMock, patch
```

**`patch` as context manager** — patches at the call boundary (module where the name is looked up, not where it is defined):

```python
with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock) as mock_close:
    await main_mod._handle_resolve("alertmanager", am_resolve())
    mock_close.assert_called_once()
    assert mock_close.call_args[0][0] == "INC-99"
```

**`patch` for Slack client** — replaces `get_client()` return value at the Slack bot module boundary:

```python
with patch("pagemenot.slack_bot.get_client", return_value=mock):
    yield mock
```

**`monkeypatch`** (pytest built-in) for patching builtins and module attributes without context managers:

```python
def test_expired_entry_not_duplicate(self, monkeypatch):
    _check_and_register("svc", "OOMKilled", "critical")
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + 99999)
    assert _check_and_register("svc", "OOMKilled", "critical") is False
```

**`AsyncMock`** for any coroutine that must be awaited:

```python
mock.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
with patch("pagemenot.main._close_jira_ticket", new_callable=AsyncMock, return_value=True):
    ...
```

---

## What Is Tested

### Pure function tests (`test_triage.py`)

No I/O, no external calls. Tests cover:

- `_dedup_key` — determinism, case-insensitivity, tuple structure
- `_check_and_register` — TTL expiry, duplicate detection, different services/titles
- `_parse_alert` — all alert sources (`alertmanager`, `pagerduty`, `grafana`, unknown), required fields, no-raise on bad input
- `_parse_crew_output` — structured dict input, prose fallback, confidence extraction, step separation (`[AUTO-SAFE]` vs `[NEEDS APPROVAL]`/`[HUMAN APPROVAL]`)
- Escalation gate logic — inlined as `_gate()` helper, tested for all severity × step combinations

### Integration tests (`test_jira_tracking.py`)

Test cross-module state and async flows with mocked Slack and Jira:

- Jira dedup dict — storage, retrieval, cross-alert independence, key stability across fire/resolve
- `_handle_resolve` — skips close when no ticket tracked; closes ticket on match; removes from tracking on success; retains on failure; clears dedup registry; clears PD tracking; Slack message content assertions

---

## What Is Not Tested

No tests exist for:

- `slack_bot.py` event handlers (`handle_approve`, `handle_reject`, `_do_triage`, etc.)
- `crew.py` — CrewAI crew construction and agent execution
- `tools.py` — real integration tools (Prometheus, Loki, GitHub, kubectl, etc.)
- `mock_tools.py` — mock tool output formatting
- `rag.py` — ChromaDB ingestion and retrieval
- `main.py` — FastAPI webhook endpoints, HMAC verification, rate limiting
- End-to-end triage flow (requires LLM + Slack)

---

## Simulation Script (not pytest)

`scripts/simulate_incident.py` sends HTTP POST requests to a running Pagemenot instance. Not a test suite — used for manual integration verification:

```bash
# Requires: docker compose up -d (app running on localhost:8080)
python scripts/simulate_incident.py payment-500s
python scripts/simulate_incident.py checkout-oom
python scripts/simulate_incident.py --list
python scripts/simulate_incident.py --random
python scripts/simulate_incident.py payment-500s --source alertmanager
```

Each scenario includes a complete `SCENARIOS` dict with mock metrics, logs, deploys, and k8s state. The script signs payloads with HMAC if `WEBHOOK_SECRET_*` vars are set in `.env`.

---

## Coverage Gaps to Note

When adding new tests:

1. `_parse_alert` for `sns` and `generic` (GCP) sources has no test coverage
2. `_redact_sensitive` — regex patterns for credentials/DSNs/IPs are untested
3. `_ApprovalStore` Redis and file-backed paths are untested
4. `_try_runbook_exec` execution paths (auto steps, approval gate, dry-run) are untested
