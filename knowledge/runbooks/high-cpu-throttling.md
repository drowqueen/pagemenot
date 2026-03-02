# High CPU Throttling

## Symptoms
- Container CPU throttling >50% sustained
- Increased latency without proportional error rate increase
- `container_cpu_cfs_throttled_seconds_total` spiking in Prometheus
- Requests completing but slowly; queue depth growing

## Diagnosis
1. Confirm throttling vs true CPU saturation — throttling means limit is too low, not usage too high
2. Check CPU requests vs limits — large gap causes aggressive throttling
3. Look for bursty workloads: batch jobs, GC pauses, connection storms
4. Check if throttling correlates with traffic spikes or scheduled jobs

## Remediation

### Step 1 — Identify throttled containers
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} --containers -->

### Step 2 — Check current resource limits
<!-- exec: kubectl get deployment {{ service }} -n {{ namespace }} -o jsonpath='{.spec.template.spec.containers[*].resources}' -->

### Step 3 — Check HPA status
<!-- exec: kubectl get hpa -n {{ namespace }} -->

### Step 4 — Scale out to distribute load
<!-- exec: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} -->

### Step 5 — Verify throttling reduces after scale-out
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} -->

## Escalate if
- Throttling persists after scaling — CPU limit needs tuning (config change, not runbook)
- Throttling caused by memory pressure triggering GC storms — separate issue
- All nodes are CPU-saturated — cluster capacity issue
