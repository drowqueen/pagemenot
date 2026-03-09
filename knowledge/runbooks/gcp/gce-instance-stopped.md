# GCE Instance Stopped

service: gcp-app-vm
tags: gcp, gce, compute, availability

## Symptoms
- Cloud Monitoring uptime check failing
- Application unreachable
- Instance status: `TERMINATED` or `STOPPED`

## Diagnosis

Get current instance status:

<!-- exec: gcloud compute instances describe {{ service }} --zone=us-central1-a --project=zipintel --format="value(status,lastStartTimestamp)" -->

Check for scheduled maintenance or preemption events:

<!-- exec: gcloud compute operations list --filter="targetLink~{{ service }} AND operationType=compute.instances.stop" --project=zipintel --format="table(name,status,insertTime,operationType)" -->

## Resolution

Start the stopped instance (safe to auto-execute — recovery action, no data risk):

<!-- exec: gcloud compute instances start {{ service }} --zone=us-central1-a --project=zipintel -->

## Escalation
If instance fails to start:
1. Check quota: `gcloud compute regions describe us-central1 --project=zipintel --format="value(quotas)"`
2. Check for OS-level boot errors: Cloud Console → Compute Engine → {{ service }} → Serial port output
3. If preemptible/spot: instance may need replacement — escalate to oncall
