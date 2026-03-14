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

<!-- exec: az cosmosdb show --name {{ service }} --resource-group {{ resource_group }} --query "[documentEndpoint, consistencyPolicy.defaultConsistencyLevel]" -o tsv -->

Check recent metrics (429 rate):

<!-- exec: az monitor metrics list --resource /subscriptions/$(az account show --query id -o tsv)/resourceGroups/{{ resource_group }}/providers/Microsoft.DocumentDB/databaseAccounts/{{ service }} --metric TotalRequests --filter "StatusCode eq '429'" --interval PT1M --output table -->

## Resolution

Scale up throughput on the database (temporary surge capacity):

<!-- exec:approve: az cosmosdb sql database throughput update --account-name {{ service }} --resource-group {{ resource_group }} --name pagemenot-db --throughput 2000 -->

## Escalation
1. If throughput increase doesn't clear 429s within 5 min, check for hot partition key
2. Escalate to app team to review query patterns
3. Consider enabling autoscale: `az cosmosdb sql database throughput migrate --throughput-type autoscale`
