# Pod CrashLoopBackOff

service: general
date: 2026-01-01

## Symptoms
- Pod status: `CrashLoopBackOff`
- Kubernetes restarting pods with increasing backoff
- Service degraded or unavailable

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --previous --tail=50 -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -o wide -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Exit code 137 (OOMKill) at memory limit
- Crash in init container (secrets/config mount issue)
- All replicas crashing simultaneously (bad ConfigMap or Secret)
