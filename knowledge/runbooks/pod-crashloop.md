# Pod CrashLoopBackOff

## Symptoms
- Pod status: `CrashLoopBackOff`
- Kubernetes restarting pods repeatedly with increasing backoff delay
- Service degraded or unavailable depending on replica count

## Diagnosis
1. Check restart count and last exit code
2. Read crash logs from the previous container instance
3. Determine if crash is OOMKill, config error, or application exception

## Remediation

### Step 1 — Inspect pod state
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Read crash logs
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --previous --tail=50 -->

### Step 3a — If OOMKilled: check memory trend, consider temporary scale-out
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -o wide -->

### Step 3b — If config error: roll back last deploy
<!-- exec: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

### Step 4 — Verify pods stabilize
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -w -->

## Escalate if
- Exit code 137 (OOMKill) and memory limit is already at maximum
- Crash is in init container — likely a secrets or config mount issue
- All replicas crashing simultaneously — possible bad ConfigMap or Secret
