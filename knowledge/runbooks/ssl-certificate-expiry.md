# SSL Certificate Expiry

service: general
date: 2026-01-01

## Symptoms
- Certificate expiring in <14 days
- Client errors: `SSL_ERROR_RX_RECORD_TOO_LONG`, `certificate has expired`
- HTTPS health checks failing

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl describe ingress -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->
<!-- exec: kubectl get secret {{ service }}-tls -n {{ namespace }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Remediation
<!-- exec:approve: kubectl delete secret {{ service }}-tls -n {{ namespace }} 2>&1 || echo "kubectl unavailable - manual action required" -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} 2>&1 || echo "kubectl unavailable - no cluster configured" -->

## Escalate if
- cert-manager cannot reach ACME issuer (rate limit or DNS)
- Certificate managed outside Kubernetes
- Wildcard cert managed by third-party CA
