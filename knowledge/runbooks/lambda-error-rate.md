# Lambda High Error Rate — Auto-Remediation

service: pagemenot-lambda-demo
tags: lambda, errors, serverless

## Symptoms
- CloudWatch `Errors` metric >= 1 in a 60s window
- Lambda function returning unhandled exceptions

## Diagnosis

Check last 5 error log events:

<!-- exec: aws logs filter-log-events --log-group-name /aws/lambda/{{ service }} --filter-pattern ERROR -->

Check current function configuration:

<!-- exec: aws lambda get-function-configuration --function-name {{ service }} -->

## Resolution

List recent versions to identify rollback candidate:

<!-- exec: aws lambda list-versions-by-function --function-name {{ service }} -->

Roll back to previous version (requires approval — replace VERSION with output above):

<!-- exec:approve: aws lambda update-alias --function-name {{ service }} --name stable --function-version VERSION -->

## Escalation
If errors persist after 2 consecutive alarm periods:
1. Check for recent deploys via `aws lambda list-versions-by-function`
2. Review CloudWatch Logs: `/aws/lambda/{{ service }}`
3. Roll back to previous version manually
