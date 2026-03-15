---
service: cloud-sql
tags: gcp, cloud-sql, database, availability
---

# Cloud SQL Instance Unavailable

## Symptoms
- Application DB connections refused or timing out
- Cloud Monitoring `cloudsql.googleapis.com/database/up` metric = 0
- Cloud SQL instance state: STOPPED or MAINTENANCE

## Diagnosis

Check current instance state:

<!-- exec: gcloud sql instances describe {{ service }} --project=${GCP_PROJECT} --format="value(state,databaseVersion,settings.tier)" -->

List recent operations for the instance:

<!-- exec: gcloud sql operations list --instance={{ service }} --project=${GCP_PROJECT} --limit=5 --format="table(name,status,operationType,startTime)" -->

## Resolution

Restart the instance (safe to auto-execute — service restart, no data loss):

<!-- exec: gcloud sql instances restart {{ service }} --project=${GCP_PROJECT} --quiet --async -->

If the instance is in a failed state, patch it back to RUNNABLE:

<!-- exec:approve: gcloud sql instances patch {{ service }} --project=${GCP_PROJECT} --activation-policy=ALWAYS --quiet -->

## Escalation
If instance fails to restart:
1. Check for maintenance window: `gcloud sql instances describe {{ service }} --project=${GCP_PROJECT} --format="value(settings.maintenanceWindow)"`
2. Check storage usage: `gcloud sql instances describe {{ service }} --project=${GCP_PROJECT} --format="value(settings.dataDiskSizeGb,settings.storageAutoResize)"`
3. Escalate to oncall if instance in ERROR state longer than 5 minutes
