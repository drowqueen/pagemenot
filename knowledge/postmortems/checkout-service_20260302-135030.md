# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

**Incident Postmortem Narrative**

### What Happened and Impact
On 2026-03-02T13:40:00, the checkout-service experienced a sudden increase in error rates and latency due to an optimized cart pricing calculation logic bug introduced by PR #1456. Within 5 minutes, three pods were killed due to Out Of Memory (OOM) errors, causing critical service downtime. The incident resulted in increased customer complaints and negatively impacted business operations.

### Root Cause Analysis
The root cause of the incident was a bug introduced by PR #1456, which optimized cart pricing calculation logic but failed to account for large cart data processing scenarios. This led to excessive CPU usage and memory consumption, ultimately causing OOM errors and pod crashes. The evidence collected indicates that error rates and latency started increasing as early as 2026-03-02T13:40:00, suggesting a gradual build-up of the issue before it reached critical levels.

### Resolution Summary
The incident was resolved through an automated investigation process ([AUTO-SAFE]) which identified the bug in the optimized cart pricing calculation logic. The fix was implemented promptly to rectify the issue and prevent similar occurrences in the future.

### Prevention Recommendations
- Conduct thorough code reviews for new PRs, especially those that introduce performance optimizations.
- Implement automated testing and monitoring tools to detect potential issues before they reach critical levels.
- Regularly review and update service-level agreements (SLAs) and error budgets to ensure alignment with business requirements and customer expectations.

## Root Cause

Bug introduced by PR #1456 ('optimize cart pricing calculation')

## Evidence

- Increased error rates and latency starting from 2026-03-02T13:40:00
- CPU usage and memory usage exceeded normal ranges starting from 2026-03-02T13:45:00
- Error logs indicate OOM errors and high memory usage when processing large cart data

## Remediation

- [AUTO-SAFE] Investigate the bug in the optimized cart pricing calculation logic and fix it.

## Similar Incidents

- N/A
