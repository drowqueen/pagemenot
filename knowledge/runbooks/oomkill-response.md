# Runbook: Pod OOMKilled

**Service:** any
**Trigger:** CrashLoopBackOff with OOMKilled reason, memory alerts

## Diagnosis

1. Confirm OOMKill:
   <!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->

2. Check memory usage trend:
   <!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} --sort-by=.status.startTime -->

3. Check if correlated with traffic spike or recent deploy

## Immediate Fix

1. If traffic spike: increase memory limits temporarily
   ```
   kubectl set resources deployment/<service> -n {{ namespace }} --limits=memory=4Gi
   ```

2. If deploy-related: rollback (see rollback-procedure.md)

3. If memory leak: investigate, then escalate — do not restart automatically

## Root Cause Investigation

1. Get heap dump if possible (Java: jmap, Go: pprof, Python: tracemalloc)
2. Check for unbounded caches, connection pools, or goroutine/thread leaks
3. Review recent code changes affecting memory allocation patterns

## Escalation

If pods keep OOMKilling after 15 minutes, page the service owner.
