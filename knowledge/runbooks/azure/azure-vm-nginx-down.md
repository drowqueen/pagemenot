---
service: azure-vm
tags: azure, vm, nginx, availability
cloud_provider: azure
---

# Azure VM — nginx Down

## Symptoms
- Port 80 HTTP probe failing, nginx process crashed or stopped
- VM is running and reachable but web server is down
- NOT for deallocated or powered-off VMs — use azure-vm-stopped.md instead
- Resource ID: microsoft.compute/virtualmachines

## Diagnosis

Check nginx status via run-command (no SSH needed):

<!-- exec: az vm run-command invoke --resource-group {{ resource_group }} --name {{ service }} --command-id RunShellScript --scripts "systemctl is-active nginx || echo nginx_down" --query "value[0].message" -o tsv -->

## Resolution

Restart nginx via run-command (safe to auto-execute — stateless):

<!-- exec: az vm run-command invoke --resource-group {{ resource_group }} --name {{ service }} --command-id RunShellScript --scripts "systemctl restart nginx && systemctl is-active nginx" --query "value[0].message" -o tsv -->

## Escalation
If nginx fails to restart:
1. Check application logs: run `journalctl -u nginx --no-pager -n 50`
2. Check for port conflict: run `ss -tlnp | grep :80`
3. Escalate to oncall — may require config fix or rollback
