# Pod CrashLoopBackOff

service: general
tags: kubernetes, k8s, crashloop, pod
date: 2026-01-01

## Symptoms
- Pod status: `CrashLoopBackOff`
- Kubernetes restarting pods with increasing backoff
- Service degraded or unavailable

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --previous --tail=50 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -o wide 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Exit code 137 (OOMKill) at memory limit
- Crash in init container (secrets/config mount issue)
- All replicas crashing simultaneously (bad ConfigMap or Secret)
