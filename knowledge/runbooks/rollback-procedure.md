# Service Rollback Procedure

service: general
date: 2026-01-01

## Symptoms
- Deploy-correlated errors or regression after release

## Diagnosis
<!-- exec: kubectl rollout history deployment/{{ service }} -n {{ namespace }} -->

## Remediation
<!-- exec:approve: kubectl rollout undo deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl rollout status deployment/{{ service }} -n {{ namespace }} -->

## Escalate if
- Rollback doesn't resolve in 5 minutes
