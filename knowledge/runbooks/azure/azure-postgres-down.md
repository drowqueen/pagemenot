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

<!-- exec:approve: STATE=$(az postgres flexible-server show --name {{ service }} --resource-group pagemenot-rg --query "state" -o tsv); if [ "$STATE" = "Stopped" ]; then az postgres flexible-server start --name {{ service }} --resource-group pagemenot-rg --no-wait; else echo "Server already in $STATE state — no start needed"; fi -->

Wait until server reaches Ready state (polls every 15s, up to 10 min):

<!-- exec: az postgres flexible-server wait --name {{ service }} --resource-group pagemenot-rg --custom "state=='Ready'" --interval 15 --timeout 600 -->

Confirm final state:

<!-- exec: az postgres flexible-server show --name {{ service }} --resource-group pagemenot-rg --query "state" -o tsv -->

## Escalation
1. If start fails, check quota: `az postgres flexible-server list --resource-group pagemenot-rg`
2. Check recent errors in server logs
3. Escalate to DBA team if data integrity concern
