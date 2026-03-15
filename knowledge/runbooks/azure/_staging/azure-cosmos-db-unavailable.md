---
service: azure-cosmos
tags: azure, cosmos, cosmosdb, serverless, database, unavailable, 503, connectivity, down
cloud_provider: azure
---

# Azure Cosmos DB Unavailable

Covers: Cosmos DB account returning 503 / connection failures; endpoint unreachable; serverless account cold-start failure.

## Symptoms
- Application errors: 503 ServiceUnavailable from Cosmos DB endpoint
- Azure Monitor alert: availability < 100% or request failure rate > 0
- Cosmos DB serverless endpoint not responding to health checks

## Diagnosis

Check account state and consistency policy:

<!-- exec: az cosmosdb show --name {{ service }} --resource-group pagemenot-rg --query "{status:provisioningState,locations:locations[].locationName,failoverPolicies:failoverPolicies[].locationName}" -o json -->

Check recent availability metrics:

<!-- exec: az monitor metrics list --resource /subscriptions/$(az account show --query id -o tsv)/resourceGroups/pagemenot-rg/providers/Microsoft.DocumentDB/databaseAccounts/{{ service }} --metric ServiceAvailability --interval PT5M --output table -->

## Resolution

If provisioning state is not "Succeeded", wait for it to stabilise — Cosmos DB serverless cold-starts can take up to 30s. Check endpoint connectivity:

<!-- exec: az cosmosdb show --name {{ service }} --resource-group pagemenot-rg --query "documentEndpoint" -o tsv -->

## Escalation
1. If `provisioningState` is stuck in "Creating" or "Updating" > 10 min: open Azure support ticket
2. Check https://status.azure.com for regional Cosmos DB incidents
3. Escalate to on-call if application is fully down and failover is not available
