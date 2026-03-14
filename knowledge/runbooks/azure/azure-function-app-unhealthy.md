---
service: azure-func
tags: azure, functions, function-app, func, serverless, availability, stopped, unhealthy, restart, functionapp
cloud_provider: azure
---

# Azure Function App Unhealthy

## Symptoms
- Function executions failing or timing out; health check failing
- Alert: "health check failing" or function app unhealthy
- HTTP trigger not responding; function app health probe failing
- Resource ID: microsoft.web/sites (kind: functionapp)

## Diagnosis

Check Function App state:

<!-- exec: az functionapp show --resource-group pagemenot-rg --name pagemenot-test-func --query "state" -o tsv -->

Check recent function failures:

<!-- exec: az monitor metrics list --resource /subscriptions/$(az account show --query id -o tsv)/resourceGroups/pagemenot-rg/providers/Microsoft.Web/sites/pagemenot-test-func --metric FunctionExecutionCount --interval PT1M --output table -->

## Resolution

Restart the Function App (safe to auto-execute — stateless, Consumption plan):

<!-- exec: az functionapp restart --resource-group pagemenot-rg --name pagemenot-test-func -->

## Escalation
If restart does not restore execution within 5 minutes:
1. Check for deployment issues: `az functionapp deployment list --resource-group pagemenot-rg --name pagemenot-test-func`
2. Check host.json and app settings: `az functionapp config appsettings list --resource-group pagemenot-rg --name pagemenot-test-func`
3. Escalate to oncall — may require redeployment
