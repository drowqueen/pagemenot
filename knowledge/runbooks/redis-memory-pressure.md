# Redis Memory Pressure

service: redis
date: 2026-01-01

## Symptoms
- `used_memory` approaching `maxmemory`
- Eviction rate spiking: `redis_evicted_keys_total` increasing
- App errors: `OOM command not allowed`
- Cache hit rate dropping

## Remediation
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=50 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->

## Escalate if
- Redis is primary data store (eviction = data loss)
- Memory growth from specific key pattern (app fix required)
- Multiple Redis instances affected
- `LOADING` state persists after restart
