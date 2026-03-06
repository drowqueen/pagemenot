# High Error Rate (5xx)

service: general
date: 2026-01-01

## Symptoms
- HTTP 5xx error rate >5% for >2 min
- `http_requests_total{status=~"5.."}` spike

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=50 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe service/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl rollout history deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual rollback required" -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Error rate >5% after rollback
- No recent deploy to roll back
- Errors in a dependency (DB, external API)
