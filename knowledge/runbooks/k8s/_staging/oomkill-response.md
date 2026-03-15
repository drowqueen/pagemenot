# Pod OOMKilled

service: general
tags: kubernetes, k8s, oom, memory
date: 2026-01-01

## Symptoms
- `CrashLoopBackOff` with OOMKilled reason
- Memory alerts firing

## Diagnosis
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} --sort-by=.status.startTime 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl set resources deployment/{{ service }} -n {{ namespace }} --limits=memory=4Gi 2>&1 || echo "kubectl unavailable - manual action required" -->

## Escalate if
- Pods keep OOMKilling after 15 min (page service owner)
- Memory leak suspected (investigate before restarting)
- All replicas OOMKilling (capacity issue)
