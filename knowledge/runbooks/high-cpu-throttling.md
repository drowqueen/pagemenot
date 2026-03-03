# High CPU Throttling

service: general
date: 2026-01-01

## Symptoms
- Container CPU throttling >50% sustained
- Latency increase without proportional error rate increase
- `container_cpu_cfs_throttled_seconds_total` spiking

## Diagnosis
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} --containers -->
<!-- exec: kubectl get deployment {{ service }} -n {{ namespace }} -o jsonpath='{.spec.template.spec.containers[*].resources}' -->
<!-- exec: kubectl get hpa -n {{ namespace }} -->

## Remediation
<!-- exec:approve: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} -->
<!-- exec: kubectl top pods -n {{ namespace }} -l app={{ service }} -->

## Escalate if
- Throttling persists after scaling (CPU limit tuning required)
- Throttling from GC storms (separate memory pressure issue)
- All nodes CPU-saturated (cluster capacity planning)
