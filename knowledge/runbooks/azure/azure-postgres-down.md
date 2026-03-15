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

<!-- exec: az postgres flexible-server show --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --query "{state:state,version:version,fqdn:fullyQualifiedDomainName}" -o json -->

## Resolution

<!-- exec: STATE=$(az postgres flexible-server show --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --query "state" -o tsv); if [ "$STATE" = "Stopping" ]; then az postgres flexible-server wait --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --custom "state=='Stopped'" --interval 15 --timeout 120; STATE="Stopped"; fi; if [ "$STATE" = "Stopped" ]; then az postgres flexible-server start --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --no-wait; else echo "Server already in $STATE state — no start needed"; fi -->

<!-- exec: az postgres flexible-server wait --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --custom "state=='Ready'" --interval 15 --timeout 600 -->

<!-- exec: az postgres flexible-server show --name {{ service }} --resource-group ${AZURE_RESOURCE_GROUP} --query "state" -o tsv -->

## Escalation
1. If start fails, check quota: `az postgres flexible-server list --resource-group ${AZURE_RESOURCE_GROUP}`
2. Check recent errors in server logs
3. Escalate to DBA team if data integrity concern
