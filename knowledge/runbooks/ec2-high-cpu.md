# EC2 High CPU

service: ec2
date: 2026-01-01

## Symptoms
- EC2 instance `CPUUtilization` > 90% sustained
- SSH unresponsive or slow
- Applications on the instance timing out

## Diagnosis
<!-- exec: aws ec2 describe-instances --instance-ids {{ service }} -->
<!-- exec: aws cloudwatch describe-alarms-for-metric --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value={{ service }} -->
<!-- exec: aws cloudwatch describe-instance-status --instance-ids {{ service }} -->

## Process-level diagnostics
Requires SSM — see TODO: SSM exec support.
Connect manually: `ssh ec2-user@<public-ip>` then `top`, `ps aux --sort=-%cpu | head -20`

## Remediation
<!-- exec:approve: aws ec2 reboot-instances --instance-ids {{ service }} -->

## Escalate if
- CPU remains high after reboot (runaway process or malicious workload)
- Instance is unresponsive to reboot (hardware issue — contact AWS Support)
- CPU spike correlates with a recent deploy (roll back)
