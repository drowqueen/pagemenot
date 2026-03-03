# High Latency

service: general
date: 2026-01-01

## Symptoms
- P99 latency >2x baseline for >3 min
- Requests completing slowly, not timing out

## Diagnosis
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl get hpa -n {{ namespace }} -->
<!-- exec: kubectl describe service/{{ service }} -n {{ namespace }} -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Latency in database (query optimization needed)
- CPU throttling at capacity limit
- Latency in external API (circuit breaker required)
