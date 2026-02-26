# INC-189: Payment Service 500 Errors After Deploy

**Date:** 2025-12-12
**Service:** payment-service
**Severity:** Critical
**Duration:** 23 minutes
**Root Cause:** Missing field validation after Stripe API upgrade

## Summary

Payment service started returning HTTP 500 errors at 02:14 UTC, affecting 15% of checkout transactions. The error rate spiked from 0.1% to 15.2% within 3 minutes.

## Timeline

- 02:11 UTC — Deploy #4489 merged (PR #847: "Upgrade Stripe SDK to v12")
- 02:14 UTC — Error rate crosses 5% threshold, PagerDuty alert fires
- 02:16 UTC — On-call SRE acknowledges alert
- 02:20 UTC — Logs show `KeyError: 'payment_intent_id'` in stripe webhook handler
- 02:25 UTC — Correlated with deploy #4489, confirmed Stripe SDK v12 changed response schema
- 02:30 UTC — Rollback to deploy #4488 initiated
- 02:34 UTC — Error rate returns to baseline

## Root Cause

Stripe SDK v12 renamed `payment_intent_id` to `payment_intent` in webhook payloads. The upgrade PR did not update the webhook handler to use the new field name. No integration tests covered this specific field mapping.

## Resolution

1. Rolled back to deploy #4488 (Stripe SDK v11)
2. Added field validation and fallback logic for both field names
3. Added integration test for Stripe webhook payload parsing
4. Re-deployed with fix as deploy #4495

## Action Items

- [x] Add integration tests for all Stripe webhook field mappings
- [x] Add defensive parsing with fallback field names
- [ ] Set up canary deploys for payment-service
- [ ] Add Stripe API changelog monitoring to deploy checklist
