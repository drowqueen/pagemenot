# SSL Certificate Expiry

service: general
date: 2026-01-01

## Symptoms
- Certificate expiring in <14 days
- Client errors: `SSL_ERROR_RX_RECORD_TOO_LONG`, `certificate has expired`
- HTTPS health checks failing

## Diagnosis
<!-- exec: kubectl get pods -n {{ namespace }} -l app={{ service }} -->
<!-- exec: kubectl describe ingress -n {{ namespace }} -->
<!-- exec: kubectl get secret {{ service }}-tls -n {{ namespace }} -->

## Remediation
<!-- exec:approve: kubectl delete secret {{ service }}-tls -n {{ namespace }} -->
<!-- exec: kubectl describe pods -n {{ namespace }} -l app={{ service }} -->

## Escalate if
- cert-manager cannot reach ACME issuer (rate limit or DNS)
- Certificate managed outside Kubernetes
- Wildcard cert managed by third-party CA
