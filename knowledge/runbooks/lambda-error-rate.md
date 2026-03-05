# Lambda High Error Rate — Auto-Remediation

service: pagemenot-lambda-demo
tags: lambda, errors, serverless

## Symptoms
- CloudWatch `Errors` metric >= 1 in a 60s window
- Lambda function returning unhandled exceptions

## Diagnosis

Check last 5 error invocations via CloudWatch Logs Insights:

<!-- exec: aws logs filter-log-events --log-group-name /aws/lambda/{{ service }} --filter-pattern "ERROR" --max-items 5 --region eu-west-1 --query 'events[*].message' --output text 2>&1 | head -20 -->

Check current function configuration (runtime, timeout, memory):

<!-- exec: aws lambda get-function-configuration --function-name {{ service }} --region eu-west-1 --query '{Runtime:Runtime,Timeout:Timeout,MemorySize:MemorySize,LastModified:LastModified}' --output json 2>&1 -->

## Resolution

Redeploy the last stable version (alias `stable` if configured, else `$LATEST`):

<!-- exec: aws lambda list-versions-by-function --function-name {{ service }} --region eu-west-1 --query 'Versions[-2:].{Version:Version,LastModified:LastModified}' --output json 2>&1 -->

## Escalation
If errors persist after 2 consecutive alarm periods:
1. Check for recent deploys — `aws lambda list-versions-by-function`
2. Review CloudWatch Logs: `/aws/lambda/{{ service }}`
3. Roll back to previous version manually
