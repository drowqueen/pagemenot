# Kafka Consumer Lag

service: general
date: 2026-01-01

## Symptoms
- Consumer group lag growing continuously
- `kafka_consumergroup_lag > threshold` sustained
- Downstream services receiving stale data

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 --since=5m 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get hpa -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=20 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- Poison message requiring DLQ intervention
- Consumer restart causes duplicates without idempotency (app team)
- Broker unhealthy (Kafka operations team)
- Lag is intentional backfill
