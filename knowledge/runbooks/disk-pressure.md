# Disk Pressure / Volume Full

## Symptoms
- Node condition: `DiskPressure=True`
- Pods evicted or failing to start: `no space left on device`
- Log writes failing, database refusing new writes

## Diagnosis
1. Identify which node and volume is full
2. Determine what is consuming disk: logs, core dumps, temp files, DB data
3. Check if log rotation is configured and working

## Remediation

### Step 1 — Identify affected nodes and pods
<!-- exec: kubectl get nodes -o wide -->
<!-- exec: kubectl describe nodes -->

### Step 2 — Check pod disk usage
<!-- exec: kubectl get pods -n production -l app={{ service }} -->

### Step 3 — Check for evicted pods
<!-- exec: kubectl get pods -n production --field-selector=status.phase=Failed -->

### Step 4 — Delete completed/evicted pods to free metadata
<!-- exec: kubectl delete pods -n production --field-selector=status.phase=Succeeded -->

### Step 5 — Verify node pressure cleared
<!-- exec: kubectl get nodes -->

## Escalate if
- Disk is full due to database growth — requires volume expansion
- Node disk cannot be cleared without data loss
- Multiple nodes affected simultaneously — storage infrastructure issue
