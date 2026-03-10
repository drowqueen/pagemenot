# Codebase Concerns

## Known Bugs

### `gce-nginx-stopped.md` — Missing `--tunnel-through-iap` in exec tags
- **Files**: `knowledge/runbooks/gce-nginx-stopped.md` lines 15, 19, 25
- The exec tags use `gcloud compute ssh ... --project=zipintel` without `--tunnel-through-iap`.
- `TODO.md` notes this was fixed in the session handoff, but the committed runbook file does not include the flag. SSH from inside the container to GCE VMs without public SSH access will fail.

### `get_event_loop()` deprecated call
- **File**: `pagemenot/main.py` line 1193
- `asyncio.get_event_loop().run_in_executor(...)` is used inside an async context that already has a running loop. In Python 3.10+ this emits a `DeprecationWarning`; in Python 3.12+ it raises `RuntimeError` when there is no current event loop in some thread contexts. All other call sites use `asyncio.get_running_loop()` correctly.

### `_alarm_incidents` not populated for the approval path
- **File**: `pagemenot/main.py` lines 789, 1064
- `_alarm_incidents` is populated only for `source == "sns"` non-auto-resolved incidents. When an incident is auto-resolved and enters CW verification (`_verify_cw_recovery`), and an SNS OK arrives before the poll completes, the SNS handler calls `_alarm_incidents.pop(alarm_name, None)` and finds nothing — Jira/PD are not closed via the SNS path. Closure still happens via `_verif_store.pop()`, but the Slack "Recovered" thread message is not posted for the verification path.

### `_ApprovalStore.get_all()` does not read from Redis
- **File**: `pagemenot/slack_bot.py` lines 100–102
- `get_all()` returns `dict(self._mem)` — always in-memory/file, never Redis. On startup resume (`main.py` line 126), pending verifications stored in Redis during the previous run are silently skipped. Only file-backed verifications are resumed.

### Datadog severity mapping collapses all non-error types to `medium`
- **File**: `pagemenot/triage.py` line 146
- `"critical" if payload.get("alert_type") == "error" else "medium"` — `alert_type` values of `warning`, `no_data`, and `snapshot` all resolve to `medium`. A `warning` alert can mean high CPU or elevated error rate that should be `high`.

### NewRelic severity mapping is binary
- **File**: `pagemenot/triage.py` lines 155–160
- Only maps `CRITICAL` → `critical`; everything else (including `HIGH` and `WARNING`) → `medium`. This suppresses PD escalation for high-severity NR incidents.

### GCP generic source severity always `high` for open
- **File**: `pagemenot/triage.py` line 214
- `severity = "high" if state == "open" else "low"` — no concept of the alert's actual severity level. Every open GCP incident pages PD if `PAGEMENOT_PD_MIN_SEVERITY=high`.

---

## Tech Debt

### `_guess_service` is a fragile heuristic
- **File**: `pagemenot/triage.py` lines 259–264
- Splits on whitespace and returns the first token containing `-` or `_`. On Datadog payloads without a `service` tag, on the `generic` fallback, and on the else branch for unknown sources, this is the service identifier. A payload like `"CPU at 95% on db-prod"` → service is `db-prod`. A payload with no hyphens/underscores → `"unknown"`. Runbook RAG matching and dedup both depend on the service name being accurate.

### RAG runbook matching uses `n_results=1` by default
- **File**: `pagemenot/config.py` line 142, `pagemenot/tools.py` lines 1197–1200
- `PAGEMENOT_RAG_RUNBOOKS_N_RESULTS=1` means only the single best-matching runbook is checked for exec steps. If the cosine similarity is low or the alert title matches a generic runbook (e.g. `high-error-rate.md`) instead of a specific one (e.g. `gce-nginx-stopped.md`), the wrong exec steps run.

### `_chroma_client()` never uses `CHROMA_HOST`
- **File**: `pagemenot/tools.py` lines 594–599, `pagemenot/rag.py` lines 38, 111
- `settings.chroma_host` is defined in `config.py` (line 31) and documented as required for multi-replica. Neither `tools.py` nor `rag.py` checks it — both always create `PersistentClient(path=...)`. Remote ChromaDB is silently ignored.

### AWS Dockerfile stage untested with `USER` fix
- **File**: `Dockerfile`, noted in `TODO.md` line 66
- The `aws` stage had a `Permission denied` bug during `apt-get` (same as the `gcp`/`azure`/`cloud` stages). The fix (`USER root` before apt-get, `USER appuser` after) was applied but the `aws` stage has not been rebuilt since. The fix may be incomplete or the stage may produce a broken image.

### `exec_shell` uses `shell=True`
- **File**: `pagemenot/tools.py` lines 873–895
- `subprocess.run(command, shell=True, ...)` is used for all non-kubectl, non-aws, non-http exec steps. This covers `gcloud` commands. While the exec tag origin is validated (must match `<!-- exec: ... -->` regex and come from a runbook file), template variable substitution with user-derived data (service name) passes through `_safe_service_name()`, which only checks `[a-zA-Z0-9_\-\.]+`. A service name containing shell metacharacters would be caught, but this is a narrow validation — any future template variable added without equivalent sanitisation creates an injection path.

### `_looks_like_alert` triggers on common words
- **File**: `pagemenot/slack_bot.py` lines 962–1001
- Keywords include `"high"`, `"warning"`, `"cpu"`, `"memory"`, `"down"`, `"500"`. Any Slack message in a watched channel containing these words triggers a full triage cycle (LLM + tools). A message like `"The meeting is at 5:00, CPU usage was high yesterday"` fires a triage.

### `_parse_crew_output` regex parsing is fragile
- **File**: `pagemenot/triage.py` lines 303–348
- Root cause extraction searches for marker strings in LLM output and takes `lines[1]` after the marker. If the LLM changes formatting or omits the marker, `result.root_cause` falls back to `"See detailed analysis below."`. Confidence detection has 5 overlapping regex patterns that can match non-confidence text (e.g. `"| low"` in a Markdown table anywhere in the output).

### Dedup key uses Python `hash()` — not collision-safe across restarts
- **File**: `pagemenot/triage.py` lines 35–36
- `str(hash(title.lower()[:60]))` uses Python's built-in `hash()`, which is randomised per-process (PYTHONHASHSEED). Keys computed in one process are invalid after restart. Since `_active_incidents` is in-memory only, this is survivable — but it means dedup state is always lost on restart regardless.

### `pagemenot_autoapprove_delay` only applies to Slack path
- **File**: `pagemenot/slack_bot.py` lines 756–780, `pagemenot/main.py` (no autoapprove logic)
- Webhook-triggered triages (`_auto_triage`) never apply the autoapprove timer. High-confidence approval-gated steps go directly to Slack buttons with no auto-execution. The feature only works for manual `/pagemenot triage` invocations and `@mention` events.

---

## Security

### Webhook secrets are optional and default to `None`
- **File**: `pagemenot/config.py` lines 111–118, `pagemenot/main.py` lines 46–54
- If a `WEBHOOK_SECRET_*` env var is not set, `_check_sig` logs a warning and accepts the request without verification. Any unauthenticated party can send arbitrary JSON to any webhook endpoint and trigger triage + potential runbook execution. Default deploy posture is unauthenticated.

### `exec_shell` with `shell=True` on gcloud commands
- **File**: `pagemenot/tools.py` line 885
- `gcloud` commands route through `exec_shell(cmd)` (the `else` branch in `dispatch_exec_step`, line 1182). They execute with `shell=True`. The service name substitution is validated, but compound `--command="..."` arguments in GCE SSH exec steps are passed through directly. A malformed or maliciously crafted runbook exec tag with shell metacharacters in the `--command` value could escape the intended command.

### Jira credentials sent as `Basic` auth in every HTTP call
- **File**: `pagemenot/main.py` lines 603–610
- `base64.b64encode(f"{email}:{api_token}".encode())` is computed inline on every Jira API call. No credential caching, but the concern is that the `jira_sm_api_token` appears in stack traces if an exception occurs before the request is made.

### PD `From` email auto-discovered via unauthenticated list
- **File**: `pagemenot/main.py` lines 600–610
- If `PAGERDUTY_FROM_EMAIL` is not set, the code fetches `/users?limit=1` to get the first user's email and uses it as the `From` header on incident creation. This is an account enumeration side effect and the email may not represent the correct requester.

### Rate limit is global, not per-source
- **File**: `pagemenot/config.py` line 89, `pagemenot/main.py` line 34
- `pagemenot_webhook_rate_limit = "60/minute"` is a single global limit applied by `get_remote_address`. Different alert sources share the same quota. A burst from one source (e.g. Alertmanager firing 60 alerts) blocks all other sources for the remainder of the minute.

---

## Performance

### Triage crew blocks a `ThreadPoolExecutor` thread for the entire LLM call
- **File**: `pagemenot/triage.py` line 444, `triage.py` line 27
- `_executor = ThreadPoolExecutor(max_workers=3)` — max 3 concurrent triages. Each holds a thread for the full LLM round-trip (4+ minutes on Ollama/llama3.1). A burst of 4+ simultaneous alerts queues behind the first 3.

### ChromaDB `ingest_all` runs synchronously at startup, blocking lifespan
- **File**: `pagemenot/main.py` line 68, `pagemenot/rag.py` line 34
- `ingest_all()` is called directly in the `lifespan` context before yielding. On a large knowledge base, startup is delayed. Health check endpoint returns 200 only after this completes.

### Re-index loop runs `ingest_all` every hour unconditionally
- **File**: `pagemenot/main.py` lines 178–186
- No change detection — re-indexes all files whether or not anything changed. On a large postmortems directory this is CPU + disk I/O every hour.

### `_resolve_pagerduty_incident` fetches user list to resolve `From` email on every call
- **File**: `pagemenot/main.py` lines 715–730
- When `PAGERDUTY_FROM_EMAIL` is not set, every PD resolution makes an extra HTTP GET to `/users?limit=1`. This is a blocking network call on the hot path for incident recovery.

---

## Incomplete Features

### No `exec_gcp_cli` — gcloud routes through `exec_shell`
- **Files**: `pagemenot/tools.py` line 1182, `TODO.md` lines 103–109
- The `dispatch_exec_step` else-branch sends `gcloud` commands to `exec_shell(cmd)`. There is no dedicated `exec_gcp_cli` function with structured error handling, timeout reporting, or credential injection. Error messages from `gcloud` are returned raw as `RuntimeError(detail[:300])`.

### No `exec_ssm` — SSM exec steps not implemented
- **File**: `TODO.md` lines 95–101
- `<!-- exec:ssm: ... -->` tag type is planned but not handled in `dispatch_exec_step`. If such a tag appears in a runbook, it falls through to `exec_shell` and runs `ssm:...` as a literal shell command.

### Cross-instance dedup requires Redis but Redis is optional
- **File**: `pagemenot/triage.py` lines 31–57, `TODO.md` line 86
- `_active_incidents` is in-memory per process. Multi-replica deployments without Redis will duplicate Jira tickets and PD incidents. The config has `redis_url` for the approval store, but dedup never uses Redis.

### No escalation timeout
- **File**: `TODO.md` line 73
- No mechanism to escalate if an incident goes unresolved after N minutes. Only CW alarm timeout (verification path) triggers escalation. Manual Slack triage, non-SNS webhook incidents, and rejected approvals rely on PD itself for escalation timing.

### Azure and full GCP webhook support not implemented
- **File**: `TODO.md` lines 102–119
- No `/webhooks/gcp` dedicated endpoint; GCP uses `/webhooks/generic`. No Azure support at all. The `generic` endpoint has no signature verification specific to Cloud Monitoring.

### Approval audit log not written
- **File**: `TODO.md` line 87
- `who approved what, when, outcome` is not persisted anywhere. The postmortem captures `resolved_by` (Slack user ID), but approval timestamps, step details, and rejections are not stored.

---

## Fragile Areas

### GCP service name extraction for `uptime_url` resources
- **File**: `pagemenot/triage.py` lines 203–212
- For resource types other than `cloud_run_revision`, `gce_instance`, `gke_container`, and `k8s_container`, the code applies a heuristic: use `resource_display_name` only if it contains `-` or `_`. Otherwise falls back to `labels.service_name` then `_guess_service(condition_name)`. Uptime check alerts for IP addresses or bare domain names return `"unknown"` as service, causing runbook RAG to match generically.

### Hardcoded GCP project and zone in runbooks
- **Files**: `knowledge/runbooks/cloud-run-unavailable.md`, `knowledge/runbooks/gce-instance-stopped.md`, `knowledge/runbooks/gce-nginx-stopped.md`
- All GCP exec tags hardcode `--project=zipintel` and `--zone=us-central1-a`. These runbooks cannot be used by other teams or in other projects/zones without manual editing. No template variable exists for `{{ project }}` or `{{ zone }}`.

### `get_runbook_exec_steps` silently returns empty on any exception
- **File**: `pagemenot/tools.py` lines 1222–1228
- The entire function is wrapped in `try/except Exception` and returns `{"auto": [], "approve": []}` on any error — including ChromaDB connection failures, collection not found, and file I/O errors. A broken ChromaDB silently disables all autonomous remediation with no alerting.

### `_parse_alert` for `generic` source falls back to `str(payload)` as title
- **File**: `pagemenot/triage.py` lines 221–227
- When a generic webhook payload lacks `incident`, `text`, and `description` keys, `text = str(payload)` is used, and `title = text[:100]`. The entire serialized dict (potentially including credentials or large nested structures) becomes the alert title passed to the LLM.

### `_verify_cw_recovery` has no circuit breaker for repeated boto3 failures
- **File**: `pagemenot/main.py` lines 820–830
- Failed `describe_alarms` calls log a warning and continue polling. 20 consecutive boto3 failures (e.g. network partition, expired credentials) consume the full `PAGEMENOT_VERIFY_TIMEOUT` (default 300s) before escalating. Each failed poll is a blocking `run_in_executor` call holding the thread.

### SNS region parsing regex only matches `^[a-z]+-[a-z]+-\d$`
- **File**: `pagemenot/main.py` lines 808–812
- Pattern `^[a-z]+-[a-z]+-\d$` matches `us-east-1`, `eu-west-1` but fails for `ap-southeast-1` (3-part regions). For `ap-southeast-1`, the human-readable field `"Asia Pacific (Singapore)"` is passed as `region`, the regex fails, and `settings.aws_region` is used as fallback. CW polling then queries the default region rather than the alarm's actual region.

### `_approval_store` file path is hardcoded
- **File**: `pagemenot/slack_bot.py` lines 39, 106
- `_FILE = "/app/data/approvals.json"` and `_verif_store = _ApprovalStore(file="/app/data/verifications.json")`. Not configurable. Local dev outside Docker has no `/app/data/` directory; the store silently falls back to in-memory on load failure (line 57 catches the `FileNotFoundError`).

### Circular import worked around with runtime import + callback injection
- **File**: `pagemenot/main.py` lines 80–90, `pagemenot/slack_bot.py` line 22
- `_post_verification_task = None` is set at module level in `slack_bot.py` and injected by `main.py` at startup. If `handle_approve` is called before lifespan completes (unlikely but possible in tests), `_post_verification_task` is `None` and CW verification is silently skipped (line 280: `if alarm_name and not dry_run and _post_verification_task`).
