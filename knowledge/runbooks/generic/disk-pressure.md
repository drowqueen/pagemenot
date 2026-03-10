# Disk Pressure

service: general
tags: kubernetes, k8s, disk, node
date: 2026-01-01

## Symptoms
- Node condition: `DiskPressure=True`
- Pods evicted: `no space left on device`
- Log writes failing, database refusing writes

## Diagnosis
<!-- exec: kubectl get nodes -o wide 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe nodes 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get pods -n {{ namespace }} --field-selector=status.phase=Failed 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec: kubectl delete pods -n {{ namespace }} --field-selector=status.phase=Succeeded 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get nodes 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Disk full from database growth (volume expansion required)
- Node disk cannot be cleared without data loss
- Multiple nodes affected (storage infrastructure issue)
