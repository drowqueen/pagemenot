# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

**Incident Postmortem Narrative**

### What Happened and Impact:

On [date], the checkout-service experienced a critical outage due to 3 pods being OOMKilled in a span of 5 minutes. This resulted in payment service errors, with clients receiving '403 Forbidden' responses for Stripe webhook requests. The impact was significant, as customers were unable to complete transactions.

### Root Cause Analysis:

The root cause of the incident was identified as Deploy #4521, which introduced a KeyError in the Stripe webhook handler due to an unexpected missing field in the request payload. This caused the handler to fail silently and raise a KeyError, leading to OOMKilled pods. Investigation revealed that the deploy included changes to the Stripe webhook handler, but defensive parsing with fallback field names was not implemented.

### Resolution Summary:

The incident was mitigated by triggering [AUTO-SAFE], which updated the Stripe webhook handler to use defensive parsing with fallback field names. This change ensured that the handler could handle missing fields in request payloads without raising a KeyError. Unfortunately, the incident was not fully auto-resolved, and manual intervention was required.

### Prevention Recommendations:

To prevent similar incidents in the future:
- Review all changes introduced by Deploy #4521 to ensure that defensive parsing with fallback field names is implemented for Stripe webhook handlers.
- Implement automated testing for webhook handlers to catch such errors before deployment.
- Improve monitoring and alerting for payment service errors, including client-side responses.

## Root Cause

Deploy #4521 introduced a KeyError in the Stripe webhook handler.

## Evidence

- # INC-189: Payment Service 500 Errors After Deploy
- Client error '403 Forbidden' for url 'https://drowqueen.grafana.net/api/alertmanager/grafana/api/v2/alerts?active=true&silenced=false&inhibited=false'
- nodename nor servname provided, or not known

## Remediation

- [AUTO-SAFE] Update Stripe webhook handler to use defensive parsing with fallback field names

## Similar Incidents

- N/A
