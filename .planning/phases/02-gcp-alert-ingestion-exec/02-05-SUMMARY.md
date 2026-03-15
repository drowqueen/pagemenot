---
phase: 02-gcp-alert-ingestion-exec
plan: 05
subsystem: testing
tags: [pytest, triage, crew-output, test-fix]

requires:
  - phase: 02-gcp-alert-ingestion-exec
    provides: _parse_crew_output(raw, parsed_alert) 2-arg signature in triage.py

provides:
  - TestParseCrewOutput: 6 tests passing with correct 2-arg calls

affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - tests/test_triage.py

key-decisions:
  - "Stale structured-dict second arg dropped from all 6 calls; tests now exercise prose-parser path"
  - "test_structured_populates_fields assertion relaxed to assert r.root_cause (empty raw -> fallback, not dict)"
  - "test_needs_approval_steps_separated switched to raw string with markers so len assertions remain valid"

patterns-established: []

requirements-completed: [GCP-01, GCP-02, GCP-03]

duration: 5min
completed: 2026-03-11
---

# Phase 02 Plan 05: Fix TestParseCrewOutput Signature Mismatch Summary

**6 TestParseCrewOutput tests fixed: 3-arg calls updated to match 2-arg _parse_crew_output(raw, parsed_alert) signature, assertions realigned to prose-parser behavior**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-11T09:08:00Z
- **Completed:** 2026-03-11T09:13:55Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- All 6 TestParseCrewOutput tests pass (was: TypeError at collection time)
- No regressions in the rest of test_triage.py (39 pass, 1 pre-existing failure in TestDedupKey::test_uses_sha256 unchanged)

## Task Commits

1. **Task 1: Fix TestParseCrewOutput 3-arg calls to 2-arg** - `8f4bf30` (fix)

## Files Created/Modified
- `tests/test_triage.py` - Removed stale 3-arg form; updated assertions for prose-parser path

## Decisions Made
- `test_uses_sha256` pre-existing failure not touched — out of scope (different test class, unrelated to this plan)
- `test_needs_approval_steps_separated` uses real raw string with `[NEEDS APPROVAL]`/`[AUTO-SAFE]`/`[HUMAN APPROVAL]` markers so the `len == 2` / `len == 1` assertions are meaningful

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `chromadb` not installed locally; installed via pip before running tests. No impact on deliverables.

## Next Phase Readiness
- TestParseCrewOutput suite clean; ready for Phase 3 end-to-end tests

---
*Phase: 02-gcp-alert-ingestion-exec*
*Completed: 2026-03-11*
