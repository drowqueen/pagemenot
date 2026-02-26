# INC-215: API Gateway Latency Spike from Certificate Renewal

**Date:** 2026-01-15
**Service:** api-gateway
**Severity:** High
**Duration:** 12 minutes
**Root Cause:** TLS certificate renewal triggered mass reconnection storm

## Summary

API gateway P99 latency spiked from 50ms to 3.2s at 03:00 UTC when the automated cert-manager renewal triggered simultaneous TLS renegotiation across all upstream connections.

## Root Cause

cert-manager renewed the wildcard TLS certificate at 03:00 UTC. The gateway's connection pool dropped all existing connections and renegotiated TLS simultaneously, creating a thundering herd. The connection pool had no staggered reconnect logic.

## Resolution

1. Latency self-recovered as connections re-established
2. Added staggered connection pool refresh (jitter of 0-30s)
3. Moved cert renewal to low-traffic window (Tuesday 04:00 UTC)

---

# INC-223: Database Connection Pool Exhaustion

**Date:** 2026-01-22
**Service:** user-service
**Severity:** Critical
**Duration:** 35 minutes
**Root Cause:** Slow query from unindexed column caused connection pool starvation

## Summary

user-service became unresponsive at 09:15 UTC. All API calls returned 504 Gateway Timeout. Investigation revealed the PostgreSQL connection pool was exhausted.

## Root Cause

A new feature (PR #1203, deployed at 08:45 UTC) added a query filtering users by `last_login_at` — a column without an index. Under production data volume (2.3M rows), each query took ~8 seconds. Connection pool (max 20) filled up within minutes as requests queued.

## Resolution

1. Killed long-running queries
2. Added index on `users.last_login_at` (took 4 minutes on production)
3. Added query timeout of 5s at the connection pool level
4. Added slow query alerting (>1s)

## Action Items

- [x] Add index on last_login_at
- [x] Add query timeout configuration
- [x] Add mandatory EXPLAIN ANALYZE for queries on tables >100k rows in PR review
- [ ] Implement connection pool monitoring dashboard
