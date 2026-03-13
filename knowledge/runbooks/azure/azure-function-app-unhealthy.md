---
service: azure-func
tags: azure, functions, serverless, availability
cloud_provider: azure
---

# Azure Function App Unhealthy

## Symptoms
- Function executions failing or timing out
- Grafana / Azure Monitor availability alert firing
- Resource ID: microsoft.web/sites (kind: functionapp)

## Diagnosis

Check Function App state:

<!-- exec: az functionapp show --resource-group pagemenot-rg --name {{ service }} --query "state" -o tsv -->

Check recent function failures:

<!-- exec: az monitor metrics list --resource /subscriptions/$(az account show --query id -o tsv)/resourceGroups/pagemenot-rg/providers/Microsoft.Web/sites/{{ service }} --metric FunctionExecutionCount --interval PT1M --output table -->

## Resolution

Restart the Function App (safe to auto-execute — stateless, Consumption plan):

<!-- exec: az functionapp restart --resource-group pagemenot-rg --name {{ service }} -->

## Escalation
If restart does not restore execution within 5 minutes:
1. Check for deployment issues: `az functionapp deployment list --resource-group pagemenot-rg --name {{ service }}`
2. Check host.json and app settings: `az functionapp config appsettings list --resource-group pagemenot-rg --name {{ service }}`
3. Escalate to oncall — may require redeployment
