# Database Connection Pool Exhaustion

service: general
date: 2026-01-01

## Symptoms
- All requests returning 504 or timing out
- `QueuePool limit reached` in logs
- DB CPU normal, app CPU low (requests queued)

## Diagnosis
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

## Remediation
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl describe service/{{ service }} -n {{ namespace }} -->

## Escalate if
- Restart does not clear backlog within 3 min
- Slow queries from missing index (DB team required)
- Pool exhaustion recurs within 10 min (config change needed)
