# High CPU Throttling

service: general
date: 2026-01-01

## Symptoms
- Container CPU throttling >50% sustained
- Latency increase without proportional error rate increase
- `container_cpu_cfs_throttled_seconds_total` spiking

## Diagnosis
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} --containers 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get deployment {{ service }} -n {{ namespace }} -o jsonpath='{.spec.template.spec.containers[*].resources}' 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get hpa -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Throttling persists after scaling (CPU limit tuning required)
- Throttling from GC storms (separate memory pressure issue)
- All nodes CPU-saturated (cluster capacity planning)
