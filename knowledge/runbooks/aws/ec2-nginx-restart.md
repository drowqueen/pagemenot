# EC2 Nginx Service Down — Restart Procedure

service: ec2-nginx
tags: ec2, nginx, service-down

## Symptoms
- HTTP health check returning non-200 or timing out
- CloudWatch StatusCheckFailed or application-level health check failing
- Nginx process not responding

## Diagnosis

Check current nginx status and recent errors:

<!-- exec: curl -sf http://{{ service }}/ --max-time 5 -o /dev/null -w "HTTP %{http_code}" || echo "Service unreachable" -->

Check last 20 nginx access/error log lines:

<!-- exec: curl -sf http://{{ service }}/health --max-time 5 || echo "Health endpoint not responding" -->

## Resolution

Restart the nginx service. This causes a brief interruption (< 2s under normal load):

<!-- exec:approve: curl -sf http://{{ service }}/ --max-time 10 --retry 3 --retry-delay 3 -o /dev/null -w "Post-restart check: HTTP %{http_code}" && echo " — nginx responding" || echo " — nginx still down, escalate" -->

## Escalation
If nginx does not respond after restart, check:
1. EC2 instance status checks in CloudWatch
2. Security group rules (port 80/443 open)
3. Disk space (`df -h`) — nginx fails silently when /var is full
