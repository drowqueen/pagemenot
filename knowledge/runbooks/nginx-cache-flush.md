# Nginx Cache Stale / High Miss Rate

service: nginx-cache
date: 2026-03-03

## Symptoms
- Cache hit rate <40% for >5 minutes
- Origin request rate elevated 3–5x normal
- P99 latency up 200–400ms (origin round-trips)
- Logs show repeated cache MISS for same paths

## Remediation

### Step 1 — Check pod status
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Check deployment history for recent changes
<!-- exec: kubectl describe deployment/{{ service }} -n {{ namespace }} -->

### Step 3 — Check logs for cache key errors
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=30 -->

### Step 4 — Roll back deploy that changed cache key prefix
<!-- exec: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->

### Step 5 — Verify rollback and pod health
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Rollback fails (no revision history) — escalate to infra team
- Cache miss persists after rollback — cache key logic bug, escalate to app team
