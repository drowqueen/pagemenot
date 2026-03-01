# SSL/TLS Certificate Expiry

## Symptoms
- Alert: certificate expiring in <14 days
- Browser/client errors: `SSL_ERROR_RX_RECORD_TOO_LONG`, `certificate has expired`
- Health checks failing on HTTPS endpoints

## Diagnosis
1. Confirm certificate expiry date
2. Check if cert-manager is configured and why auto-renewal failed
3. Check if certificate is managed manually or via cert-manager

## Remediation

### Step 1 — Check certificate status
<!-- exec: kubectl get certificates -n production -->
<!-- exec: kubectl describe certificate {{ service }}-tls -n production -->

### Step 2 — Check cert-manager logs for renewal errors
<!-- exec: kubectl logs -n cert-manager -l app=cert-manager --tail=50 -->

### Step 3 — Trigger manual renewal if auto-renewal is stuck
<!-- exec: kubectl delete secret {{ service }}-tls -n production -->

cert-manager will recreate the secret and re-issue within 60–120 seconds.

### Step 4 — Verify new certificate issued
<!-- exec: kubectl get certificates -n production -->
<!-- exec: kubectl get secret {{ service }}-tls -n production -->

## Escalate if
- cert-manager cannot reach the ACME issuer (Let's Encrypt rate limit or DNS issue)
- Certificate is managed outside Kubernetes — requires manual renewal by infra team
- Wildcard cert managed by a third party CA
