---
phase: 04-azure-monitor-support-and-testing
plan: "02"
subsystem: infra
tags: azure, webhooks, triage, rag, chromadb, azure-monitor, az-cli

requires:
  - phase: 04-azure-monitor-support-and-testing
    plan: "01"
    provides: "RED tests for Azure parse, webhook, dispatch, and RAG (TestParseAlertAzure, TestDispatchExecAzure, TestAzureRunbooks)"

provides:
  - "elif source == 'azure' branch in triage._parse_alert() — severity mapping Sev0-Sev4, service from alertTargetIDs last segment"
  - "/webhooks/azure FastAPI endpoint — Fired accepted, Resolved skipped+dedup cleared"
  - "az login --service-principal in lifespan — non-fatal on failure"
  - "webhook_secret_azure Optional[str] config field"
  - "_detect_cloud_provider() alias in rag.py (singular, returns first provider string)"
  - "knowledge/runbooks/azure/azure-vm-stopped.md and azure-app-service-down.md with exec: steps"
  - "cloudbuild.yaml --target=cloud (was --target=gcp)"
  - "TestAzureRunbooks class in test_rag_filtering.py"

affects:
  - 04-azure-monitor-support-and-testing/04-03
  - 04-azure-monitor-support-and-testing/04-04

tech-stack:
  added: []
  patterns:
    - "Azure Monitor webhook follows same pattern as /webhooks/generic: sig check, monitorCondition=Resolved skips, else accepted"
    - "az login scoped to lifespan with import subprocess as _sp (module-namespace-safe)"
    - "Azure runbooks use cloud_provider: azure frontmatter + azure tag for RAG dir-hint detection"

key-files:
  created:
    - knowledge/runbooks/azure/azure-vm-stopped.md
    - knowledge/runbooks/azure/azure-app-service-down.md
  modified:
    - pagemenot/triage.py
    - pagemenot/main.py
    - pagemenot/config.py
    - pagemenot/rag.py
    - cloudbuild.yaml
    - tests/test_rag_filtering.py
    - tests/test_triage.py

key-decisions:
  - "az login uses scoped 'import subprocess as _sp' inside lifespan to avoid polluting module namespace"
  - "os.makedirs('/app/.azure', exist_ok=True) before az login to prevent PermissionError on first run"
  - "_detect_cloud_provider() alias added to rag.py (singular wrapper) — test file imported singular name, plural function already existed; alias preserves both"
  - "TestDispatchExecAzure test fixed: raw command → <!-- exec: --> wrapped (test was RED by design, fix aligns with function's security contract)"

patterns-established:
  - "Azure runbook exec steps use az prefix, routed by exec_shell via dispatch_exec_step (no new routing)"
  - "cloud_provider: azure in runbook frontmatter + azure in tags = ingested with is_azure=1 flag in ChromaDB"

requirements-completed: [AZ-01, AZ-02, AZ-03, AZ-04, AZ-05, AZ-06, AZ-07]

duration: 20min
completed: 2026-03-11
---

# Phase 4 Plan 02: Azure Monitor Support Summary

**Azure Monitor webhook + parse branch + az CLI auth + two runbooks turn 18 Azure RED tests GREEN; cloudbuild target switched to `cloud` for multi-cloud CLI availability**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-11T11:24:00Z
- **Completed:** 2026-03-11T11:44:56Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- `_parse_alert("azure", payload)` handles full Azure Monitor Common Alert Schema — Sev0-Sev4 mapping, service from alertTargetIDs last path segment, legacy payload fallback
- `/webhooks/azure` endpoint with HMAC sig check, Resolved → skipped+dedup, Fired → accepted
- Azure runbooks with `az vm start`, `az webapp restart`, and diagnostic exec steps ingested by RAG with `cloud_provider: azure` metadata

## Task Commits

1. **Task 1: Azure parse branch + config fields** - `9df7387` (feat)
2. **Task 2: /webhooks/azure + az login lifespan + _detect_cloud_provider alias** - `679e5d2` (feat)
3. **Task 3: Azure runbooks, cloud build target, RAG tests** - `ba3f44e` (feat)

## Files Created/Modified
- `pagemenot/triage.py` - elif source == "azure" block inserted before generic branch
- `pagemenot/config.py` - webhook_secret_azure field added
- `pagemenot/main.py` - /webhooks/azure endpoint + az login in lifespan
- `pagemenot/rag.py` - _detect_cloud_provider() singular alias
- `cloudbuild.yaml` - --target=gcp → --target=cloud
- `knowledge/runbooks/azure/azure-vm-stopped.md` - created with 3 exec: steps
- `knowledge/runbooks/azure/azure-app-service-down.md` - created with 3 exec: steps
- `tests/test_rag_filtering.py` - TestAzureRunbooks class appended
- `tests/test_triage.py` - TestDispatchExecAzure fixed (raw cmd → wrapped)

## Decisions Made
- `_detect_cloud_provider` singular alias added to rag.py — test_rag_filtering.py imported it by that name, actual function is plural; alias returns first element
- `os.makedirs("/app/.azure", exist_ok=True)` before az login — prevents PermissionError in containers without pre-created directory
- TestDispatchExecAzure fixed to pass `<!-- exec: ... -->` wrapper — raw command was intentional RED per plan 04-01; fix aligns test with security contract of dispatch_exec_step

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] _detect_cloud_provider import error in test_rag_filtering.py**
- **Found during:** Task 3 (TestAzureRunbooks)
- **Issue:** test_rag_filtering.py imports `_detect_cloud_provider` (singular) but rag.py only exports `_detect_cloud_providers` (plural) — ImportError blocked all tests in the file
- **Fix:** Added `_detect_cloud_provider` alias in rag.py that wraps plural and returns `[0]`
- **Files modified:** pagemenot/rag.py
- **Verification:** `pytest tests/test_rag_filtering.py::TestAzureRunbooks -x -q` passes; import resolves
- **Committed in:** 679e5d2 (Task 2 commit)

**2. [Rule 1 - Bug] TestDispatchExecAzure passing raw command to dispatch_exec_step**
- **Found during:** Task 3 (full azure test run)
- **Issue:** Test called `dispatch_exec_step("az vm start ...")` without HTML comment wrapper; function raises ValueError on untagged steps (security enforcement). Was plan 04-01 intentional RED.
- **Fix:** Wrapped arg in `<!-- exec: az vm start ... -->` to match function contract
- **Files modified:** tests/test_triage.py
- **Verification:** `pytest tests/ -k azure -x -q` passes (18/18)
- **Committed in:** ba3f44e (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary to turn RED tests GREEN. No scope creep.

## Issues Encountered
- Pre-existing RED tests unrelated to Azure (TestDedupKey::test_uses_sha256, TestJiraTracking errors) remain unchanged — out of scope per deviation rules

## Next Phase Readiness
- All Azure tests green (18 passing)
- Runbooks ingested with is_azure=1 flag — get_runbook_exec_steps('Azure ...', cloud_providers=['azure']) returns exec steps after ingest_all()
- Plan 04-03: Cloud Build trigger needed to ship --target=cloud Docker image to production VM

---
*Phase: 04-azure-monitor-support-and-testing*
*Completed: 2026-03-11*
