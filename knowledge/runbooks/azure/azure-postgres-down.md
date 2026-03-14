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

<!-- exec: az postgres flexible-server show --name pagemenot-postgres --resource-group pagemenot-rg --query "{state:state,version:version,fqdn:fullyQualifiedDomainName}" -o json -->

## Resolution

Start the stopped server:

<!-- exec:approve: az postgres flexible-server start --name pagemenot-postgres --resource-group pagemenot-rg -->

Verify server is running:

<!-- exec: az postgres flexible-server show --name pagemenot-postgres --resource-group pagemenot-rg --query "state" -o tsv -->

## Escalation
1. If start fails, check quota: `az postgres flexible-server list --resource-group pagemenot-rg`
2. Check recent errors in server logs
3. Escalate to DBA team if data integrity concern
