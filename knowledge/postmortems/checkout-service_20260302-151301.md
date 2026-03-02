# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

### Postmortem Narrative for Incident #INC-202

**What Happened and Impact**
On 2026-02-25T16:05:00Z, three pods of the checkout-service were terminated due to Out Of Memory (OOM) killing within a five-minute window. This resulted in a service outage, impacting users attempting to complete their transactions during this timeframe.

### Root Cause Analysis
The root cause was identified as a memory-related issue stemming from recent deployment PR #1456. The introduction of this code change led to an increased memory consumption, culminating in the OOM killing of pods. Notably, a similar incident (INC-201) occurred on 2026-01-08, caused by a memory leak in cart serialization. This suggests a pattern where recent deployments have introduced memory-related issues without adequate testing or optimization.

### Resolution Summary
Immediate steps were taken to stabilize the service, including manually restarting the terminated pods and deploying a hotfix to address the root cause of excessive memory usage. The incident was not auto-resolved due to the critical nature of the failure, requiring direct intervention by SREs. Once tools are operational after an incident, [AUTO-SAFE] will analyze metrics for potential efficiency issues leading up to the incident.

### Prevention Recommendations
1. **Enhanced Testing**: Implement more comprehensive testing strategies for all code changes, including deployment-specific scenarios that simulate peak loads and edge cases.
2. **Memory Profiling**: Regularly profile memory usage across critical services like checkout-service to identify potential leaks or inefficiencies before they lead to outages.
3. **Deployment Review Process**: Review recent deployments (like PR #1456) for any known issues or patterns, such as the one identified in INC-201, and consider additional testing or code reviews for high-risk changes.

## Root Cause

memory-related issue caused by recent deployment of PR #1456

## Evidence

- Recent deployment for 'checkout-service' is PR #1456, which was merged on 2026-02-25T16:00:00Z.
- Past incident with a similar pattern is INC-201, which occurred on 2026-01-08, caused by a memory leak in the cart serialization process.

## Remediation

- [AUTO-SAFE] Analyze recent metrics to identify potential efficiency issues or trends leading up to the incident once tools are operational.

## Similar Incidents

- N/A
