# Cloud Run Service Unavailable

service: gcp-hello
tags: gcp, cloud-run, ingress, availability
alert: Cloud Run uptime check failing, Cloud Run service unavailable

## Symptoms
- HTTP 403 or connection refused from external clients
- Cloud Monitoring uptime check failing
- `ingress` setting is not `all`

## Diagnosis

Check current ingress setting:

<!-- exec: gcloud run services describe {{ service }} --region=us-central1 --project=${GCP_PROJECT} --format="value(spec.template.metadata.annotations['run.googleapis.com/ingress'])" -->

Check current traffic routing and URL:

<!-- exec: gcloud run services describe {{ service }} --region=us-central1 --project=${GCP_PROJECT} --format="value(status.url,status.traffic)" -->

## Resolution

Restore external ingress (safe to auto-execute — restores availability, no data risk):

<!-- exec: gcloud run services update {{ service }} --ingress=all --region=us-central1 --project=${GCP_PROJECT} -->

If traffic was shifted away from the stable revision, roll back:

<!-- exec:approve: gcloud run services update-traffic {{ service }} --to-tags=stable=100 --region=us-central1 --project=${GCP_PROJECT} -->

## Escalation
If service remains unavailable after ingress restore:
1. Check Cloud Run logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name={{ service }}" --limit=50 --project=${GCP_PROJECT}`
2. Verify IAM invoker binding: `gcloud run services get-iam-policy {{ service }} --region=us-central1 --project=${GCP_PROJECT}`
3. Check for deployment errors in Cloud Console → Cloud Run → {{ service }} → Revisions
