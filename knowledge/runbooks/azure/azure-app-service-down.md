---
service: azure-app
tags: azure, app-service, web, availability
cloud_provider: azure
---

# Azure App Service Down

## Symptoms
- HTTP health check returning 5xx
- Azure Monitor availability alert firing
- Resource ID: microsoft.web/sites

## Diagnosis

Check App Service state:

<!-- exec: az webapp show --resource-group pagemenot-rg --name {{ service }} --query "state" -o tsv -->

Check recent application logs:

<!-- exec: az webapp log tail --resource-group pagemenot-rg --name {{ service }} --provider application -->

## Resolution

Restart the App Service (safe to auto-execute — stateless HTTP tier):

<!-- exec: az webapp restart --resource-group pagemenot-rg --name {{ service }} -->

## Escalation
If restart does not restore availability within 5 minutes:
1. Check deployment slots: `az webapp deployment slot list --resource-group pagemenot-rg --name {{ service }}`
2. Check for failed deployment: `az webapp deployment list --resource-group pagemenot-rg --name {{ service }} --query "[0]"`
3. Escalate to oncall — may require config rollback or slot swap
