# Redis Memory Pressure

service: redis
date: 2026-01-01

## Symptoms
- `used_memory` approaching `maxmemory`
- Eviction rate spiking: `redis_evicted_keys_total` increasing
- App errors: `OOM command not allowed`
- Cache hit rate dropping

## Remediation
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=50 -->
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Redis is primary data store (eviction = data loss)
- Memory growth from specific key pattern (app fix required)
- Multiple Redis instances affected
- `LOADING` state persists after restart
