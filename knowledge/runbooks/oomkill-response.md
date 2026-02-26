# Runbook: Pod OOMKilled

**Service:** any
**Trigger:** CrashLoopBackOff with OOMKilled reason, memory alerts

## Diagnosis

1. Confirm OOMKill:
   ```
   kubectl describe pod <pod-name> -n production | grep -A5 "Last State"
   ```

2. Check memory usage trend:
   ```
   kubectl top pods -n production | grep <service>
   ```

3. Check if correlated with traffic spike or recent deploy

## Immediate Fix

1. If traffic spike: increase memory limits temporarily
   ```
   kubectl set resources deployment/<service> -n production --limits=memory=4Gi
   ```

2. If deploy-related: rollback (see rollback-procedure.md)

3. If memory leak: restart pods to buy time, then investigate
   ```
   kubectl rollout restart deployment/<service> -n production
   ```

## Root Cause Investigation

1. Get heap dump if possible (Java: jmap, Go: pprof, Python: tracemalloc)
2. Check for unbounded caches, connection pools, or goroutine/thread leaks
3. Review recent code changes affecting memory allocation patterns

## Escalation

If pods keep OOMKilling after 15 minutes, page the service owner.
