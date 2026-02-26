# Runbook: Service Rollback Procedure

**Service:** any
**Trigger:** Deploy-correlated errors, regression after release

## Steps

1. Confirm the issue correlates with a recent deploy:
   - Check deploy history: `kubectl rollout history deployment/<service> -n production`
   - Compare error start time with deploy time

2. Initiate rollback:
   <!-- exec: kubectl rollout undo deployment/{{ service }} -n production -->

3. Verify rollback:
   <!-- exec: kubectl rollout status deployment/{{ service }} -n production -->

4. Confirm error rate returns to baseline in monitoring

5. Notify the team in #incidents Slack channel

6. Create a Jira ticket for the broken deploy

## Escalation

If rollback doesn't resolve the issue within 5 minutes, escalate to the service owner and platform team.
