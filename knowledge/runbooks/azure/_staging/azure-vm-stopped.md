---
service: azure-vm
tags: azure, vm, compute, availability, heartbeat, deallocate, stopped
cloud_provider: azure
---

# Azure VM Stopped / Unreachable

Covers: VM deallocated, powered off, or heartbeat absent. Not for nginx/web service failures — use azure-vm-nginx-down.md.

## Symptoms
- VM stopped, deallocated, or powered off — heartbeat absent, all metrics gone
- Azure Monitor alert: VmHeartbeat condition absent; activity log operationName `deallocate/action` or `powerOff/action`
- VM unreachable — SSH refused, no CPU/network metrics, power state = Deallocated or Stopped
- Fix: `az vm start` to power on the instance

## Diagnosis

Check VM power state:

<!-- exec: az vm show --resource-group {{ resource_group }} --name {{ service }} --query "powerState" -o tsv -->

Check recent VM activity log:

<!-- exec: az monitor activity-log list --resource-group {{ resource_group }} --offset 1h --query "[].{time:eventTimestamp, op:operationName.value, status:status.value}" -o table -->

## Resolution

Start the VM (safe to auto-execute — idempotent):

<!-- exec: az vm start --resource-group {{ resource_group }} --name {{ service }} -->

## Escalation
If VM fails to start after 2 minutes:
1. Check for quota exceeded: `az vm list-usage --location eastus -o table`
2. Check disk health in Azure Portal -> Virtual Machines -> {{ service }} -> Disks
3. Escalate to oncall if hardware fault suspected
