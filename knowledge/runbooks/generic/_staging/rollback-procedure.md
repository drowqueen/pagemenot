# Service Rollback Procedure

service: general
tags: kubernetes, k8s, rollback, deployment
date: 2026-01-01

## Symptoms
- Deploy-correlated errors or regression after release

## Diagnosis
<!-- exec: kubectl rollout history deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Rollback doesn't resolve in 5 minutes
