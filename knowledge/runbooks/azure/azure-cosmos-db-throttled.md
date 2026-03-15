---
service: azure-cosmos
tags: azure, cosmos, cosmosdb, database, throttled, 429, throughput, ru
cloud_provider: azure
---

# Azure Cosmos DB — Throttled (429 / RU Exhausted)

Covers: Cosmos DB account returning 429 TooManyRequests; provisioned RU/s exhausted.

## Symptoms
- HTTP 429 from Cosmos DB endpoint; application retries failing
- Azure Monitor alert: NormalizedRUConsumption = 100% sustained
- Request rate dropping, latency spiking

## Diagnosis

Check current throughput and consumption:

<!-- exec: az cosmosdb show --name {{ service }} --resource-group pagemenot-rg --query "[documentEndpoint, consistencyPolicy.defaultConsistencyLevel]" -o tsv -->

Check recent metrics (429 rate):

<!-- exec: az monitor metrics list --resource /subscriptions/$(az account show --query id -o tsv)/resourceGroups/pagemenot-rg/providers/Microsoft.DocumentDB/databaseAccounts/{{ service }} --metric TotalRequests --filter "StatusCode eq '429'" --interval PT1M --output table -->

## Resolution

Regenerate primary key to force client reconnection and clear stuck throttled sessions:

<!-- exec:approve: az cosmosdb keys regenerate --name {{ service }} --resource-group pagemenot-rg --key-kind primary -->

## Escalation
1. If 429s persist after key rotation, check for hot partition key
2. Escalate to app team to review query patterns
3. Consider migrating to provisioned throughput account for autoscale support
