# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

**Incident Postmortem Narrative**

### What Happened and Impact

On [Date] at 11:32:00, three pods of the checkout-service were unexpectedly killed due to Out Of Memory (OOM), resulting in a critical service outage. The error rate spiked to 15.2% within five minutes, with high latency reaching 150ms. This incident affected users attempting transactions for EU regions.

### Root Cause Analysis

The root cause was identified as Deploy #4521, which introduced a KeyError in the Stripe webhook handler. This bug caused an internal server error when handling webhooks from Stripe, leading to OOMKilled pods and service disruption. The coinciding timing of the error rate spike and high latency with the recent deployment strongly suggested this causal link.

### Resolution Summary

The incident was auto-resolved using the search_runbooks query 'Stripe webhook handler KeyError remediation', but Auto-safe resolution was False due to incomplete or inadequate runbook coverage for this specific issue. Human intervention would have been required to fully resolve the incident, likely involving additional steps such as manual deployment rollbacks or code fixes.

### Prevention Recommendations

- Enhance auto-resolution capabilities through more comprehensive and specific runbooks.
- Implement automated testing for Stripe webhook handler logic, particularly after critical deployments.
- Review post-deployment monitoring strategies to catch potential errors earlier, reducing the likelihood of OOMKilled pods due to prolonged high latency or error rates.

## Root Cause

Deploy #4521 introduced a KeyError in the Stripe webhook handler.

## Evidence

- The sudden spike in error rate (15.2% at 11:33:31) and high latency (150ms at 11:32:00) strongly suggests that the issue is related to the recent deployment, given the coinciding timing with these metrics.
- Error message 'Checkout transaction failed for EU region due to internal server error' indicates a problem specifically in the Stripe webhook handler.

## Remediation

- [AUTO-SAFE] search_runbooks(query='Stripe webhook handler KeyError remediation')

## Similar Incidents

- N/A
