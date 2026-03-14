---
service: azure-sql
tags: azure, sql, database, paused, serverless, cold-start, connection
cloud_provider: azure
---

# Azure SQL Database — Paused (Serverless Auto-Pause)

Covers: Azure SQL Serverless DB auto-paused after inactivity; connections failing with "database paused" error.

## Symptoms
- Application connection errors: "Database 'pagemenot-db' on server 'pagemenot-sql-srv' is not currently available"
- Azure Monitor alert: connection_failed > 0 after period of inactivity
- Serverless DB auto-paused (expected behaviour but triggers app alerts)

## Diagnosis

Check database status:

<!-- exec: az sql db show --resource-group pagemenot-rg --server pagemenot-sql-srv --name pagemenot-db --query "{status:status,currentSku:currentSku.name,pausedDate:pausedDate}" -o json -->

## Resolution

Resume the paused database:

<!-- exec: az sql db resume --resource-group pagemenot-rg --server pagemenot-sql-srv --name pagemenot-db -->

Verify it's online:

<!-- exec: az sql db show --resource-group pagemenot-rg --server pagemenot-sql-srv --name pagemenot-db --query "status" -o tsv -->

## Escalation
1. If resume fails, check server quota: `az sql server show --name pagemenot-sql-srv --resource-group pagemenot-rg`
2. If repeatedly auto-pausing, increase auto-pause delay or disable: `az sql db update ... --auto-pause-delay -1`
