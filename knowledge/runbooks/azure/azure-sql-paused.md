---
service: azure-sql
tags: azure, sql, database, paused, serverless, cold-start, connection
cloud_provider: azure
---

# Azure SQL Database — Paused (Serverless Auto-Pause)

Covers: Azure SQL Serverless DB auto-paused after inactivity; connections failing with "database paused" error.

## Symptoms
- Application connection errors: "Database '{{ service }}' on server is not currently available"
- Azure Monitor alert: connection_failed > 0 after period of inactivity
- Serverless DB auto-paused (expected behaviour but triggers app alerts)

## Setup
Set `AZURE_SQL_SERVER` in `.env` to your SQL server name (e.g. `my-sql-server`).
For multi-server environments, use per-service config or extend the webhook parser to extract the server name from the alert resource ID.

## Diagnosis

<!-- exec: az sql db show --resource-group ${AZURE_RESOURCE_GROUP} --server ${AZURE_SQL_SERVER} --name {{ service }} --query "{status:status,currentSku:currentSku.name,pausedDate:pausedDate}" -o json -->

## Resolution

<!-- exec: az rest --method post --url "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.Sql/servers/${AZURE_SQL_SERVER}/databases/{{ service }}/resume?api-version=2021-08-01-preview" -->

<!-- exec: az sql db show --resource-group ${AZURE_RESOURCE_GROUP} --server ${AZURE_SQL_SERVER} --name {{ service }} --query "status" -o tsv -->

## Escalation
1. If resume fails, check server quota: `az sql server show --name ${AZURE_SQL_SERVER} --resource-group ${AZURE_RESOURCE_GROUP}`
2. If repeatedly auto-pausing, increase auto-pause delay or disable: `az sql db update ... --auto-pause-delay -1`
