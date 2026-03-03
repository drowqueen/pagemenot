# Disk Pressure

service: general
date: 2026-01-01

## Symptoms
- Node condition: `DiskPressure=True`
- Pods evicted: `no space left on device`
- Log writes failing, database refusing writes

## Diagnosis
<!-- exec: kubectl get nodes -o wide -->
<!-- exec: kubectl describe nodes -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl get pods -n {{ namespace }} --field-selector=status.phase=Failed -->

## Remediation
<!-- exec: kubectl delete pods -n {{ namespace }} --field-selector=status.phase=Succeeded -->
<!-- exec: kubectl get nodes -->

## Escalate if
- Disk full from database growth (volume expansion required)
- Node disk cannot be cleared without data loss
- Multiple nodes affected (storage infrastructure issue)
