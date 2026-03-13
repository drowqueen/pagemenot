---
service: azure-vm
tags: azure, vm, compute, availability
cloud_provider: azure
---

# Azure VM Stopped / Unreachable

## Symptoms
- VM health check failing
- Azure Monitor metric absent or CPU/heartbeat alert firing
- Resource ID: microsoft.compute/virtualmachines

## Diagnosis

Check VM power state:

<!-- exec: az vm show --resource-group {{ resource_group }} --name {{ service }} --query "powerState" -o tsv -->

Check recent VM activity log:

<!-- exec: az monitor activity-log list --resource-group {{ resource_group }} --resource-type Microsoft.Compute/virtualMachines --max-events 5 --query "[].{time:eventTimestamp, op:operationName.value, status:status.value}" -o table -->

## Resolution

Start the VM (safe to auto-execute — idempotent):

<!-- exec: az vm start --resource-group {{ resource_group }} --name {{ service }} -->

## Escalation
If VM fails to start after 2 minutes:
1. Check for quota exceeded: `az vm list-usage --location eastus -o table`
2. Check disk health in Azure Portal -> Virtual Machines -> {{ service }} -> Disks
3. Escalate to oncall if hardware fault suspected
