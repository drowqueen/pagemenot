# Database Connection Pool Exhaustion

service: general
tags: database, connections
date: 2026-01-01

## Symptoms
- All requests returning 504 or timing out
- `QueuePool limit reached` in logs
- DB CPU normal, app CPU low (requests queued)

## Diagnosis
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe service/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Restart does not clear backlog within 3 min
- Slow queries from missing index (DB team required)
- Pool exhaustion recurs within 10 min (config change needed)
