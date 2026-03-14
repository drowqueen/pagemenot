---
service: azure-vm
tags: azure, vm, nginx, availability, http, port80, web, systemctl
cloud_provider: azure
---

# Azure VM — nginx Down (web server crashed, VM running)

Covers: nginx process stopped on a running VM. Not for stopped/deallocated VMs — use azure-vm-stopped.md.

## Symptoms
- nginx web server crashed or stopped; VM IS powered on and reachable
- HTTP port 80 probe returning connection refused or 502; `systemctl is-active nginx` = inactive
- Azure Monitor HTTP availability alert; VM heartbeat IS present, only nginx process down
- Fix: `az vm run-command invoke` to restart nginx remotely without SSH

## Diagnosis

Check nginx status via run-command (no SSH needed):

<!-- exec: az vm run-command invoke --resource-group {{ resource_group }} --name {{ service }} --command-id RunShellScript --scripts "systemctl is-active nginx || echo nginx_down" --query "value[0].message" -o tsv -->

## Resolution

Restart nginx via run-command (requires approval — service restart on production VM):

<!-- exec:approve: az vm run-command invoke --resource-group {{ resource_group }} --name {{ service }} --command-id RunShellScript --scripts "systemctl restart nginx && systemctl is-active nginx" --query "value[0].message" -o tsv -->

## Escalation
If nginx fails to restart:
1. Check application logs: run `journalctl -u nginx --no-pager -n 50`
2. Check for port conflict: run `ss -tlnp | grep :80`
3. Escalate to oncall — may require config fix or rollback
