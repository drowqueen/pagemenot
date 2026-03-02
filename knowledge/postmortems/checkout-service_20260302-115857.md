# Incident: checkout-service: pods OOMKilled (3 pods in 5 min)

**Service:** checkout-service
**Severity:** critical
**Date:** 2026-03-02
**Resolved automatically:** False
**Triage confidence:** high

## Root Cause

Deploy #4521 introduced a KeyError in the Stripe webhook handler.

## Evidence

- # INC-189: Payment Service 500 Errors After Deploy
- Client error '403 Forbidden' for url 'https://drowqueen.grafana.net/api/alertmanager/grafana/api/v2/alerts?active=true&silenced=false&inhibited=false'
- nodename nor servname provided, or not known

## Remediation

- [AUTO-SAFE] Update Stripe webhook handler to use defensive parsing with fallback field names

## Similar Incidents

- N/A
