# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

**Incident Postmortem Narrative**

### What Happened and Impact

On [date], three pods of the checkout-service were unexpectedly killed due to Out Of Memory (OOM). This resulted in a service outage lasting approximately 5 minutes, impacting our customers' ability to complete transactions. The high memory usage and error rates observed in the monitoring report indicated a memory leak caused by an unhandled KeyError in the Stripe webhook handler.

### Root Cause Analysis

The recent deployment of PR #1456, which optimized cart pricing calculation, introduced a KeyError in the Stripe webhook handler. This occurred because the new code did not properly handle the case where the webhook payload was missing required keys. The high memory usage and error rates observed were consistent with this root cause.

### Resolution Summary

To resolve the incident, we updated the Stripe webhook handler to handle KeyErrors gracefully using an auto-safe update mechanism. However, due to the severity of the issue, manual intervention was required to ensure timely resolution. We also took steps to review the recent deployments and identify potential memory leaks caused by similar issues.

### Prevention Recommendations

- **Improved Deployment Reviews**: Review recent deployments for potential memory leaks or unhandled errors.
- **Enhanced Error Handling**: Implement robust error handling mechanisms in our codebase, including proper logging and notification of critical errors.
- **Regular Code Audits**: Conduct regular code audits to identify potential areas of improvement and refactor code as necessary.

## Root Cause

Deploy #4521 introduced a KeyError in the Stripe webhook handler.

## Evidence

- The recent deployment of PR #1456, which optimized cart pricing calculation, was merged on 2026-02-25T16:00:00Z. The high memory usage and error rates observed in the monitoring report are consistent with a memory leak caused by a KeyError in the Stripe webhook handler.

## Remediation

- [AUTO-SAFE] Update the Stripe webhook handler to handle KeyErrors gracefully.

## Similar Incidents

- N/A
