---
service: azure-app
tags: azure, app-service, web, availability
cloud_provider: azure
---

# Azure App Service Down

## Symptoms
- HTTP health check returning 5xx or availability < 100%
- Azure Monitor availability alert: "availability < 100%" or App Service down
- App Service HTTP availability check failing
- Resource ID: microsoft.web/sites

## Diagnosis

Check App Service state:

<!-- exec: az webapp show --resource-group {{ resource_group }} --name {{ service }} --query "state" -o tsv -->

Check recent application logs:

<!-- exec: az webapp log show --resource-group {{ resource_group }} --name {{ service }} --provider application --num-lines 20 2>&1 || echo "no logs available" -->

## Resolution

Restart the App Service (safe to auto-execute — stateless HTTP tier):

<!-- exec: az webapp restart --resource-group {{ resource_group }} --name {{ service }} -->

## Escalation
If restart does not restore availability within 5 minutes:
1. Check deployment slots: `az webapp deployment slot list --resource-group {{ resource_group }} --name {{ service }}`
2. Check for failed deployment: `az webapp deployment list --resource-group {{ resource_group }} --name {{ service }} --query "[0]"`
3. Escalate to oncall — may require config rollback or slot swap
