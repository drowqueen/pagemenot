# High Latency / Slow Responses

## Symptoms
- P99 latency >2x baseline sustained for >3 minutes
- Requests completing but slowly — not timing out
- May be isolated to specific endpoints or upstream dependencies

## Diagnosis
1. Check if latency is uniform across endpoints or isolated
2. Check downstream service latency (DB, cache, external APIs)
3. Check CPU throttling and resource pressure
4. Check for GC pressure (Java/JVM services) or event loop blocking (Node.js)
5. Correlate with recent deploys or traffic increase

## Remediation

### Step 1 — Check resource pressure
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Check if traffic spike is the cause — scale out if so
<!-- exec: kubectl get hpa -n {{ namespace }} -->

### Step 3 — Verify downstream dependencies
<!-- exec: curl -sf https://{{ service }}/health -->

### Step 4 — Roll back if latency began after a deploy
<!-- exec: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Latency is in the database — requires query optimization
- CPU throttling but cannot scale further — capacity planning needed
- Latency is in an external API — outside your control, implement circuit breaker
