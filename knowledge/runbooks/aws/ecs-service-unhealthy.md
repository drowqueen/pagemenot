# ECS Service Unhealthy — Auto-Remediation

service: pagemenot-ecs-demo
tags: ecs, container, service, aws, tasks

## Symptoms
- CloudWatch `RunningTaskCount` below desired count
- ECS service shows tasks in STOPPED or PENDING state
- Service health check failures or task definition errors

## Diagnosis

Check cluster health:

<!-- exec: aws ecs describe-clusters --clusters {{ service }} -->

Check service state and task counts:

<!-- exec: aws ecs describe-services --cluster {{ service }} --services {{ service }} -->

List recently stopped tasks for failure details:

<!-- exec: aws ecs list-tasks --cluster {{ service }} --desired-status STOPPED -->

## Resolution

Force a new deployment to replace unhealthy tasks (requires approval):

<!-- exec:approve: aws ecs update-service --cluster {{ service }} --service {{ service }} --force-new-deployment -->

## Escalation
If tasks continue failing after force-new-deployment:
1. Check task definition: `aws ecs describe-task-definition --task-definition {{ service }}`
2. Check stopped task reasons: `aws ecs describe-tasks --cluster {{ service }} --tasks <task-arn>`
3. Review CloudWatch Logs for the container
4. Consider rolling back task definition to previous revision
