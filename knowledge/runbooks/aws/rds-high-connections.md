# RDS High Connections — Auto-Remediation

service: pagemenot-rds-demo
tags: rds, database, connections, aws, postgres

## Symptoms
- CloudWatch `DatabaseConnections` metric above threshold
- Application errors: "too many connections", "connection pool exhausted"
- `max_connections` parameter group limit being approached

## Diagnosis

Get current DB instance state and configuration:

<!-- exec: aws rds describe-db-instances --db-instance-identifier {{ service }} -->

Check recent DB events (last 60 minutes):

<!-- exec: aws rds describe-events --source-identifier {{ service }} --source-type db-instance --duration 60 -->

Check DB engine logs for connection errors:

<!-- exec: aws rds describe-db-log-files --db-instance-identifier {{ service }} -->

## Resolution

Force a reboot to clear stale connections and reset the connection pool (requires approval):

<!-- exec:approve: aws rds reboot-db-instance --db-instance-identifier {{ service }} -->

## Escalation
If connections remain high after reboot:
1. Check application connection pool settings (max pool size, idle timeout)
2. Consider upgrading instance class via `aws rds modify-db-instance`
3. Enable RDS Proxy to multiplex connections
