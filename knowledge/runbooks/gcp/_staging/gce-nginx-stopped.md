# GCE Nginx Service Stopped

service: gcp-app-vm
tags: gcp, gce, nginx, service, availability

## Symptoms
- HTTP uptime check failing (port 80)
- GCE instance status: RUNNING
- nginx process not in `ps aux`

## Diagnosis

Check nginx service status on the instance:

<!-- exec: gcloud compute ssh {{ service }} --zone=${GCP_ZONE} --project=${GCP_PROJECT} --command="systemctl status nginx --no-pager; true" -->

Check nginx error log:

<!-- exec: gcloud compute ssh {{ service }} --zone=${GCP_ZONE} --project=${GCP_PROJECT} --command="sudo journalctl -u nginx --no-pager -n 20; true" -->

## Resolution

Restart nginx (safe to auto-execute — service restart, no data risk):

<!-- exec: gcloud compute ssh {{ service }} --zone=${GCP_ZONE} --project=${GCP_PROJECT} --command="sudo systemctl restart nginx" -->

## Escalation
If nginx fails to start:
1. Check config syntax: `gcloud compute ssh {{ service }} --zone=${GCP_ZONE} --project=${GCP_PROJECT} --command="sudo nginx -t"`
2. Check disk space: `gcloud compute ssh {{ service }} --zone=${GCP_ZONE} --project=${GCP_PROJECT} --command="df -h"`
3. Escalate to oncall if config error requires manual fix
