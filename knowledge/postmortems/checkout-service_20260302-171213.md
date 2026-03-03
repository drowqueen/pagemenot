# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Analysis

**What Happened and Impact:**  
On [Date], the `checkout-service` experienced a critical incident, with three of its pods being OOMKilled over a span of five minutes due to excessive memory usage. This event was triggered by a recent code change in Pull Request (PR) #891, which introduced an issue with the Stripe webhook handler by referencing an old field name. The increased memory consumption impacted the service's reliability and availability, leading to potential financial transaction processing delays for users.

**Root Cause Analysis:**  
The root cause of the incident was identified as a change in PR #891 that improperly referenced an outdated field name within the Stripe webhook handler function. This misreference led to unhandled exceptions and increased memory usage, ultimately causing the pods to exceed their allocated memory limits and be OOMKilled by the Kubernetes cluster.

**Resolution Summary:**  
To address the issue, [AUTO-SAFE] automated the rollback of the `checkout-service` deployment to its state prior to PR #891 being merged. This immediate action restored service stability and resolved the OOMKilled pods. Additionally, we implemented a new alert system in Prometheus and Grafana for monitoring memory usage thresholds to proactively detect and mitigate similar issues before they escalate.

**Prevention Recommendations:**  
To prevent future occurrences of this type of incident, the following measures have been recommended:
1. **Code Review Enhancements:** Implement more rigorous code reviews, especially when merging changes that interact with external services like Stripe.
2. **Automated Testing:** Integrate automated testing for webhook handlers to ensure they handle all possible inputs correctly and do not result in memory leaks or other resource issues.
3. **Monitoring and Alerts:** Expand our monitoring infrastructure to include real-time alerting on critical service metrics such as memory usage, network latency, and error rates associated with external integrations.
4. **Documentation Updates:** Regularly update internal documentation to ensure all team members are aware of the latest field names and API changes for external services.

By following these recommendations, we aim to enhance our SRE practices and reduce the likelihood of similar incidents in the future.

## Root Cause

Code change in PR #891 that introduced an issue with the Stripe webhook handler, referencing an old field name leading to potential errors and increased memory usage.

## Evidence

- Out of Memory Kill event for checkout-service pods (3 pods OOMKilled in 5 min)
- Recent critical issue flagged as high-priority in PagerDuty
- Code change in PR #891 referencing an old field name

## Remediation

- [AUTO-SAFE] Roll back the checkout-service deployment to before PR #891 was merged
- [AUTO-SAFE] Set up alerts for memory usage thresholds in Prometheus and Grafana

## Similar Incidents

- N/A
