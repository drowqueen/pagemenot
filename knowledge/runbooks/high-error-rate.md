# High Error Rate (5xx)

## Symptoms
- HTTP 5xx error rate >5% sustained for >2 minutes
- Alerts: `http_requests_total{status=~"5.."}` spike

## Diagnosis
1. Check which endpoints are failing — error rate by route
2. Check for recent deploys in the last 30 minutes
3. Check application logs for exceptions and stack traces
4. Check downstream dependencies (DB, cache, external APIs)

## Remediation

### Step 1 — Verify the spike is real
<!-- exec: kubectl get pods -n production -l app={{ service }} -->
<!-- exec: curl -sf https://{{ service }}/health -->

### Step 2 — Check recent deploy
<!-- exec: kubectl rollout history deployment/{{ service }} -n production -->

### Step 3 — Roll back if deploy correlates
<!-- exec: kubectl rollout undo deployment/{{ service }} -n production -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n production -->

### Step 4 — Verify recovery
Wait 2 minutes and re-check error rate. If >5% persists after rollback, escalate — root cause is not the deploy.

## Escalate if
- Error rate remains >5% after rollback
- No recent deploy to roll back
- Errors are in a dependency (DB, external API) — not fixable by rollback
