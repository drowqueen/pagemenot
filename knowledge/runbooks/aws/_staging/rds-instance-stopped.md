# RDS Instance Stopped

service: pagemenot-rds-demo
tags: rds, database, availability, aws

## Symptoms
- CloudWatch `FreeStorageSpace` metric missing (no data from stopped instance)
- Application connectivity errors: "could not connect to server"
- `DBInstanceStatus` = `stopped`

## Diagnosis

Get current DB instance status:

<!-- exec: aws rds describe-db-instances --db-instance-identifier {{ service }} -->

Check recent DB events (last 30 minutes):

<!-- exec: aws rds describe-events --source-identifier {{ service }} --source-type db-instance --duration 30 -->

## Resolution

Start the stopped instance (safe to auto-execute — recovery action, no data risk):

<!-- exec: aws rds start-db-instance --db-instance-identifier {{ service }} -->

## Escalation
If instance fails to start:
1. Check `describe-db-instances` for `PendingModifiedValues` or incompatible parameters
2. Check RDS Events for engine errors
3. Verify instance is not in `incompatible-parameters` state — may need parameter group rollback
