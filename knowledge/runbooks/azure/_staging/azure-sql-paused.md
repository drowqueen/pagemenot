---
service: azure-sql
tags: azure, sql, database, paused, serverless, cold-start, connection
cloud_provider: azure
---

# Azure SQL Database — Paused (Serverless Auto-Pause)

Covers: Azure SQL Serverless DB auto-paused after inactivity; connections failing with "database paused" error.

## Symptoms
- Application connection errors: "Database '{{ resource_name }}' on server '{{ servers }}' is not currently available"
- Azure Monitor alert: connection_failed > 0 after period of inactivity
- Serverless DB auto-paused (expected behaviour but triggers app alerts)

## Diagnosis

Check database status:

<!-- exec: az sql db show --resource-group {{ resource_group }} --server {{ servers }} --name {{ resource_name }} --query "{status:status,currentSku:currentSku.name,pausedDate:pausedDate}" -o json -->

## Resolution

Resume the paused database:

<!-- exec: az sql db resume --resource-group {{ resource_group }} --server {{ servers }} --name {{ resource_name }} -->

Verify it's online:

<!-- exec: az sql db show --resource-group {{ resource_group }} --server {{ servers }} --name {{ resource_name }} --query "status" -o tsv -->

## Escalation
1. If resume fails, check server quota: `az sql server show --name {{ servers }} --resource-group {{ resource_group }}`
2. If repeatedly auto-pausing, increase auto-pause delay or disable: `az sql db update ... --auto-pause-delay -1`
