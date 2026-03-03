# Kafka Consumer Lag

service: general
date: 2026-01-01

## Symptoms
- Consumer group lag growing continuously
- `kafka_consumergroup_lag > threshold` sustained
- Downstream services receiving stale data

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 --since=5m -->
<!-- exec: kubectl get hpa -n {{ namespace }} -l app={{ service }} -->

## Remediation
<!-- exec:approve: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} -->
<!-- exec:approve: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=20 -->

## Escalate if
- Poison message requiring DLQ intervention
- Consumer restart causes duplicates without idempotency (app team)
- Broker unhealthy (Kafka operations team)
- Lag is intentional backfill
