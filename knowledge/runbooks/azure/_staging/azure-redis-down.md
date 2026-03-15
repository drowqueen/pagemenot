---
service: azure-redis
tags: azure, redis, cache, down, unavailable, connection, eviction
cloud_provider: azure
---

# Azure Redis Cache — Down / Connection Failures

Covers: Azure Cache for Redis unavailable or connection failures from application.

## Symptoms
- Application cache misses spiking; Redis connection timeouts
- Azure Monitor alert: connectedclients = 0 or usedmemory > threshold
- Cache errors: "No connection is available to service this operation"

## Diagnosis

Check Redis instance state and stats:

<!-- exec: az redis show --name {{ service }} --resource-group {{ resource_group }} --query "{provisioningState:provisioningState,hostName:hostName,port:port,sku:sku.name}" -o json -->

<!-- exec: az redis list-keys --name {{ service }} --resource-group {{ resource_group }} --query "primaryKey" -o tsv -->

## Resolution

Force reboot the Redis instance (clears stuck connections, applies pending updates):

<!-- exec: az redis force-reboot --name {{ service }} --resource-group {{ resource_group }} --reboot-type AllNodes -->

## Escalation
1. If reboot doesn't restore connections, check VNet/NSG rules
2. Check eviction policy: `az redis show --name {{ service }} --resource-group {{ resource_group }} --query redisConfiguration.maxmemory-policy`
3. Escalate to platform team if data loss suspected
