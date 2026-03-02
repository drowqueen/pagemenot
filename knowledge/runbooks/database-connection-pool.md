# Database Connection Pool Exhaustion

## Symptoms
- All requests returning 504 or timing out
- `sqlalchemy.exc.TimeoutError: QueuePool limit reached`
- DB CPU normal, app CPU low — requests queued, not processing

## Diagnosis
1. Confirm pool exhaustion in logs: `Connection pool exhausted`
2. Check for slow queries holding connections open
3. Check for connection leaks (connections not returned to pool)
4. Check DB max_connections vs pool size

## Remediation

### Step 1 — Identify blocking queries
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 -->

### Step 2 — Check pod count and health
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

### Step 3 — Restart affected pods to release leaked connections
This forces connection pool reset. Safe if DB is healthy.
<!-- exec: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

### Step 4 — Verify recovery
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

## Escalate if
- Restart does not clear the backlog within 3 minutes
- Slow queries are from a missing index — requires DB team
- Pool exhaustion recurs within 10 minutes — config change needed
