# INC-201: Checkout Service OOMKilled During Flash Sale

**Date:** 2026-01-08
**Service:** checkout-service
**Severity:** Critical
**Duration:** 45 minutes
**Root Cause:** Memory leak in cart serialization during high traffic

## Summary

During the winter flash sale, checkout-service pods began OOMKilling at 14:22 UTC. The service auto-scaled but new pods also OOMKilled within minutes. 30% of checkout attempts failed during the incident.

## Timeline

- 14:00 UTC — Flash sale begins, traffic 4x normal
- 14:22 UTC — First checkout-service pod OOMKilled
- 14:25 UTC — HPA scales to 8 pods, but new pods also OOMKilling
- 14:30 UTC — PagerDuty critical alert, on-call paged
- 14:40 UTC — Heap dump reveals unbounded cart object growth in session cache
- 14:50 UTC — Temporary fix: increase memory limit to 4Gi, restart pods
- 15:07 UTC — Service stabilized, error rate at baseline

## Root Cause

The cart serialization code created a new copy of the entire cart object on every price check API call. Under normal traffic, garbage collection kept up. During flash sale traffic (4x), the allocation rate exceeded GC capacity, causing memory pressure and eventual OOMKill.

## Resolution

1. Immediate: Increased memory limits from 2Gi to 4Gi
2. Fix: Refactored cart serialization to use references instead of copies
3. Added memory usage alerting at 70% threshold

## Action Items

- [x] Fix cart serialization memory leak
- [x] Add memory usage alerts at 70% and 85% thresholds
- [ ] Load test checkout-service at 10x normal traffic before next sale
- [ ] Implement circuit breaker for cart price-check endpoint
