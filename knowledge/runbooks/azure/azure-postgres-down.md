---
service: azure-postgres
tags: azure, postgres, postgresql, database, down, stopped, flexible-server
cloud_provider: azure
---

# Azure PostgreSQL Flexible Server — Down / Stopped

Covers: PostgreSQL Flexible Server stopped or unavailable; connections refused.

## Symptoms
- Application connection errors to PostgreSQL endpoint
- Azure Monitor alert: is_db_alive = 0 or active_connections = 0
- Server state: Stopped or Inaccessible

## Diagnosis

Check server state:

<!-- exec: az postgres flexible-server show --name {{ service }} --resource-group pagemenot-rg --query "{state:state,version:version,fqdn:fullyQualifiedDomainName}" -o json -->

## Resolution

Start the stopped server (non-blocking — returns immediately, server starts in background):

<!-- exec:approve: az postgres flexible-server start --name {{ service }} --resource-group pagemenot-rg --no-wait -->

Wait until server reaches Ready state (polls every 15s, up to 5 min):

<!-- exec:approve: az postgres flexible-server wait --name {{ service }} --resource-group pagemenot-rg --custom "state=='Ready'" --interval 15 --timeout 300 -->

## Escalation
1. If start fails, check quota: `az postgres flexible-server list --resource-group pagemenot-rg`
2. Check recent errors in server logs
3. Escalate to DBA team if data integrity concern
