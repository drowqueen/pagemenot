# Kafka Consumer Lag

## Symptoms
- Consumer group lag growing continuously (not draining)
- Alert: `kafka_consumergroup_lag > threshold` sustained
- Downstream services receiving stale data
- Producer throughput normal; consumers processing slower than ingestion rate

## Diagnosis
1. Confirm lag is growing vs stable — stable lag at high offset is less urgent
2. Check consumer pod count and health — OOMKill or crashloop stops consumption
3. Check consumer processing time — slow external calls (DB, downstream APIs) cause lag
4. Check for partition imbalance — one partition may have all the lag
5. Check broker health — producer errors or broker restarts cause temporary lag

## Remediation

### Step 1 — Check consumer pod health
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->

### Step 2 — Check consumer logs for processing errors
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=100 --since=5m -->

### Step 3 — Check HPA — scale consumers if pods are healthy but overwhelmed
<!-- exec: kubectl get hpa -n {{ namespace }} -l app={{ service }} -->

### Step 4 — Scale consumer deployment to increase parallelism
<!-- exec: kubectl scale deployment/{{ service }} --replicas=+2 -n {{ namespace }} -->

### Step 5 — Restart consumers if stuck (poison message or deadlock)
<!-- exec: kubectl rollout restart deployment/{{ service }} -n {{ namespace }} -->

### Step 6 — Verify lag starts draining
<!-- exec: kubectl logs -n {{ namespace }} -l app={{ service }} --tail=20 -->

## Escalate if
- Lag is caused by a poison message requiring DLQ intervention
- Consumer restart causes duplicate processing with no idempotency — app team required
- Broker itself is unhealthy — Kafka operations team
- Lag is intentional backfill — confirm before acting
