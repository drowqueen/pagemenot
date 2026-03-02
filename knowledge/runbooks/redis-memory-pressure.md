# Redis Memory Pressure

## Symptoms
- Redis `used_memory` approaching `maxmemory`
- Eviction rate spiking: `redis_evicted_keys_total` increasing
- Application errors: `OOM command not allowed` or `LOADING Redis is loading`
- Cache hit rate dropping due to evictions

## Diagnosis
1. Check memory usage and eviction policy — `allkeys-lru` evicts silently; `noeviction` returns errors
2. Identify top memory consumers — large keys, high cardinality sets, uncompressed values
3. Check for memory leaks: keys without TTL accumulating over time
4. Check connected clients — client output buffers can consume significant memory
5. Distinguish between cache Redis (eviction OK) and data Redis (eviction is data loss)

## Remediation

### Step 1 — Check Redis pod memory and status
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Check Redis logs for OOM or eviction messages
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=50 -->

### Step 3 — Check client connections and buffer usage
<!-- exec: kubectl exec -n {{ namespace }} deploy/{{ service }} -- redis-cli info clients -->

### Step 4 — Check memory breakdown
<!-- exec: kubectl exec -n {{ namespace }} deploy/{{ service }} -- redis-cli info memory -->

### Step 5 — Flush expired keys to reclaim memory (safe — only removes already-expired keys)
<!-- exec: kubectl exec -n {{ namespace }} deploy/{{ service }} -- redis-cli DEBUG SLEEP 0 -->

### Step 6 — Restart Redis if client buffers are the cause (clears all connections)
<!-- exec: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Redis is used as primary data store (not cache) — eviction = data loss, requires immediate escalation
- Memory growth is from a specific key pattern requiring application-level fix
- Multiple Redis instances affected — infrastructure capacity issue
- `LOADING` state persists after restart — possible RDB/AOF corruption
