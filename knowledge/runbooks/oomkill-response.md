# Pod OOMKilled

service: general
date: 2026-01-01

## Symptoms
- `CrashLoopBackOff` with OOMKilled reason
- Memory alerts firing

## Diagnosis
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} --sort-by=.status.startTime -->

## Remediation
<!-- exec:approve: kubectl set resources deployment/{{ service }} -n {{ namespace }} --limits=memory=4Gi -->

## Escalate if
- Pods keep OOMKilling after 15 min (page service owner)
- Memory leak suspected (investigate before restarting)
- All replicas OOMKilling (capacity issue)
