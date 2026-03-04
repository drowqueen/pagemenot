"""
Mock Incident Simulator — generates realistic fake monitoring data.

This is the POC magic. Teams can demo Pagemenot without connecting
real Prometheus/PagerDuty/GitHub. The mock layer generates realistic
data that the agents triage exactly as they would real incidents.

Usage:
  python scripts/simulate_incident.py payment-500s
  python scripts/simulate_incident.py checkout-oom
  python scripts/simulate_incident.py db-connection-pool
  python scripts/simulate_incident.py cert-renewal
  python scripts/simulate_incident.py traffic-spike
  python scripts/simulate_incident.py ec2-nginx-down
  python scripts/simulate_incident.py --list
  python scripts/simulate_incident.py --random
"""

import hashlib
import hmac
import json
import os
import random
import sys
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env so webhook secrets are available without exporting to shell
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        pass

PAGEMENOT_URL = os.environ.get("PAGEMENOT_URL", "http://localhost:8080")

# Webhook HMAC secrets — read from env (same vars as pagemenot config)
_SECRETS = {
    "pagerduty":    os.getenv("WEBHOOK_SECRET_PAGERDUTY", ""),
    "grafana":      os.getenv("WEBHOOK_SECRET_GRAFANA", ""),
    "alertmanager": os.getenv("WEBHOOK_SECRET_ALERTMANAGER", ""),
    "datadog":      os.getenv("WEBHOOK_SECRET_DATADOG", ""),
    "newrelic":     os.getenv("WEBHOOK_SECRET_NEWRELIC", ""),
    "generic":      os.getenv("WEBHOOK_SECRET_GENERIC", ""),
}

_SIG_HEADERS = {
    "pagerduty":    ("X-PagerDuty-Signature", "v1="),
    "grafana":      ("X-Grafana-Signature", ""),
    "alertmanager": ("X-Alertmanager-Token", ""),
    "datadog":      ("X-Datadog-Signature", ""),
    "newrelic":     ("X-NR-Webhook-Token", ""),
    "generic":      ("X-Pagemenot-Signature", "sha256="),
}


def _sign(source: str, body: bytes) -> dict:
    """Return extra headers with HMAC signature if secret is configured."""
    secret = _SECRETS.get(source, "")
    if not secret:
        return {}
    header_name, prefix = _SIG_HEADERS.get(source, ("", ""))
    if not header_name:
        return {}
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {header_name: f"{prefix}{sig}"}


# ══════════════════════════════════════════════════════════════
# INCIDENT SCENARIOS — each one is a complete mock story
# ══════════════════════════════════════════════════════════════

SCENARIOS = {
    "payment-500s": {
        "name": "Payment Service 500 Errors After Deploy",
        "pagerduty": {
            "id": "P5678901",
            "title": "payment-service: HTTP 500 error rate >5%",
            "description": "payment-service error rate spiked to 15.2% starting at 02:14 UTC. Checkout transactions failing for EU region.",
            "urgency": "high",
            "service": {"name": "payment-service", "id": "PSVC001"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.1, "after": 15.2, "unit": "%"},
            "request_rate": {"before": 1200, "after": 1150, "unit": "req/s"},
            "latency_p99": {"before": 0.12, "after": 0.45, "unit": "s"},
            "cpu_percent": {"before": 35, "after": 38, "unit": "%"},
            "memory_mb": {"before": 512, "after": 520, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-02-26T02:14:12Z ERROR payment-service KeyError: 'payment_intent_id' in handler.py:142",
            "2026-02-26T02:14:12Z ERROR payment-service Traceback: stripe_webhook_handler -> process_payment -> validate_fields",
            "2026-02-26T02:14:13Z ERROR payment-service KeyError: 'payment_intent_id' in handler.py:142",
            "2026-02-26T02:14:13Z WARN  payment-service Request failed: POST /webhooks/stripe -> 500",
            "2026-02-26T02:14:14Z ERROR payment-service 847 occurrences of KeyError in last 60s",
            "2026-02-26T02:14:15Z INFO  payment-service Health check OK (but errors continuing)",
        ],
        "mock_deploys": [
            {
                "pr": 891,
                "title": "refactor stripe webhook handler for SDK v12",
                "author": "alice",
                "merged_at": "2026-02-26T02:11:00Z",
                "files_changed": ["src/webhooks/stripe_handler.py", "src/payments/validator.py"],
                "diff_preview": "- intent_id = payload['payment_intent_id']\n+ intent_id = payload['payment_intent']  # SDK v12 rename\n  # BUG: webhook handler still uses old field name",
            },
            {
                "pr": 889,
                "title": "update monitoring dashboards",
                "author": "bob",
                "merged_at": "2026-02-25T18:30:00Z",
                "files_changed": ["monitoring/dashboards.json"],
                "diff_preview": "Updated Grafana dashboard for payment metrics",
            },
        ],
        "mock_k8s": {
            "pods": "3/3 Running",
            "restarts": 0,
            "events": "No unusual events",
            "resource_pressure": False,
        },
    },

    "checkout-oom": {
        "name": "Checkout Service OOMKilled During Traffic Spike",
        "pagerduty": {
            "id": "P9012345",
            "title": "checkout-service: pods OOMKilled (3 pods in 5 min)",
            "description": "checkout-service pods are being OOMKilled repeatedly. HPA scaled to 8 replicas but new pods also crashing. Memory usage at 98% before kill.",
            "urgency": "high",
            "service": {"name": "checkout-service", "id": "PSVC002"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.5, "after": 32.0, "unit": "%"},
            "request_rate": {"before": 800, "after": 3200, "unit": "req/s"},
            "latency_p99": {"before": 0.2, "after": 8.5, "unit": "s"},
            "cpu_percent": {"before": 45, "after": 95, "unit": "%"},
            "memory_mb": {"before": 1500, "after": 2048, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 12, "unit": ""},
        },
        "mock_logs": [
            "2026-02-26T14:22:01Z ERROR checkout-service OOMKilled: container exceeded 2Gi memory limit",
            "2026-02-26T14:22:01Z WARN  checkout-service Pod checkout-service-7f8d9-xk2m terminated (OOMKilled)",
            "2026-02-26T14:23:15Z ERROR checkout-service OOMKilled: container exceeded 2Gi memory limit",
            "2026-02-26T14:24:02Z WARN  checkout-service HPA scaled to 8 replicas (target CPU 80%, actual 95%)",
            "2026-02-26T14:25:30Z ERROR checkout-service New pod checkout-service-7f8d9-ab3n also OOMKilled after 90s",
            "2026-02-26T14:25:31Z ERROR checkout-service Memory leak suspected: heap growing 50MB/min in cart serializer",
        ],
        "mock_deploys": [
            {
                "pr": 1456,
                "title": "optimize cart pricing calculation",
                "author": "charlie",
                "merged_at": "2026-02-25T16:00:00Z",
                "files_changed": ["src/cart/serializer.py", "src/cart/pricing.py"],
                "diff_preview": "  def calculate_price(self, cart):\n+     cart_copy = deepcopy(self.cart)  # BUG: creates full copy on every call\n+     return self._compute(cart_copy)",
            },
        ],
        "mock_k8s": {
            "pods": "5/8 Running (3 CrashLoopBackOff)",
            "restarts": 12,
            "events": "OOMKilled x12, HPA scaled 3->8, Back-off restarting",
            "resource_pressure": True,
        },
    },

    "db-connection-pool": {
        "name": "Database Connection Pool Exhaustion",
        "pagerduty": {
            "id": "P3456789",
            "title": "user-service: all API requests returning 504",
            "description": "user-service is unresponsive. All requests timing out with 504 Gateway Timeout since 09:15 UTC.",
            "urgency": "high",
            "service": {"name": "user-service", "id": "PSVC003"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.01, "after": 98.5, "unit": "%"},
            "request_rate": {"before": 500, "after": 500, "unit": "req/s"},
            "latency_p99": {"before": 0.08, "after": 30.0, "unit": "s"},
            "cpu_percent": {"before": 20, "after": 15, "unit": "%"},
            "memory_mb": {"before": 400, "after": 410, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-02-26T09:15:02Z ERROR user-service Connection pool exhausted: 20/20 connections in use",
            "2026-02-26T09:15:02Z ERROR user-service Waiting for available connection... timeout after 30s",
            "2026-02-26T09:15:33Z ERROR user-service sqlalchemy.exc.TimeoutError: QueuePool limit of 20 reached",
            "2026-02-26T09:15:34Z WARN  user-service Slow query detected: SELECT * FROM users WHERE last_login_at > ... (8.2s)",
            "2026-02-26T09:16:00Z ERROR user-service 200+ requests queued waiting for DB connection",
        ],
        "mock_deploys": [
            {
                "pr": 1203,
                "title": "add last login filter to user search",
                "author": "diana",
                "merged_at": "2026-02-26T08:45:00Z",
                "files_changed": ["src/users/queries.py", "src/users/api.py"],
                "diff_preview": "+ users = db.query(User).filter(User.last_login_at > cutoff).all()\n  # NOTE: last_login_at column has no index (2.3M rows)",
            },
        ],
        "mock_k8s": {
            "pods": "3/3 Running",
            "restarts": 0,
            "events": "No pod issues — problem is database-side",
            "resource_pressure": False,
        },
    },

    "cert-renewal": {
        "name": "TLS Certificate Expiry — api-gateway cert renewal failing",
        "pagerduty": {
            "id": "P7890123",
            "title": "api-gateway: TLS certificate renewal causing connection storm",
            "description": "cert-manager renewed *.company.com at 03:00 UTC. api-gateway TLS session renegotiation storm started immediately — 5000 connections reset, P99 latency jumped from 50ms to 3.2s.",
            "urgency": "high",
            "service": {"name": "api-gateway", "id": "PSVC004"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.05, "after": 2.1, "unit": "%"},
            "request_rate": {"before": 5000, "after": 4800, "unit": "req/s"},
            "latency_p99": {"before": 0.05, "after": 3.2, "unit": "s"},
            "cpu_percent": {"before": 30, "after": 75, "unit": "%"},
            "memory_mb": {"before": 256, "after": 280, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-02-26T03:00:01Z INFO  cert-manager Certificate renewed: *.company.com",
            "2026-02-26T03:00:02Z WARN  api-gateway TLS session renegotiation storm: 5000 connections resetting",
            "2026-02-26T03:00:02Z WARN  api-gateway Connection pool drained, rebuilding all upstream connections",
            "2026-02-26T03:00:05Z WARN  api-gateway Latency spike: p99=3200ms (normal: 50ms)",
            "2026-02-26T03:05:00Z INFO  api-gateway Connections re-established, latency recovering",
            "2026-02-26T03:12:00Z INFO  api-gateway Latency back to normal: p99=52ms",
        ],
        "mock_deploys": [],
        "mock_k8s": {
            "pods": "5/5 Running",
            "restarts": 0,
            "events": "cert-manager renewal at 03:00:01 UTC",
            "resource_pressure": False,
        },
    },

    "traffic-spike": {
        "name": "Unexpected Traffic Spike from Bot Attack",
        "pagerduty": {
            "id": "P4567890",
            "title": "frontend-api: request rate 10x normal, latency degrading",
            "description": "frontend-api seeing 10x normal traffic. Latency increasing across all endpoints. Suspected bot traffic from unusual IP range.",
            "urgency": "high",
            "service": {"name": "frontend-api", "id": "PSVC005"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.1, "after": 5.0, "unit": "%"},
            "request_rate": {"before": 2000, "after": 20000, "unit": "req/s"},
            "latency_p99": {"before": 0.1, "after": 2.5, "unit": "s"},
            "cpu_percent": {"before": 40, "after": 92, "unit": "%"},
            "memory_mb": {"before": 800, "after": 1200, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-02-26T10:00:01Z WARN  frontend-api Traffic anomaly: 20000 req/s (normal: 2000)",
            "2026-02-26T10:00:02Z WARN  frontend-api 85% of requests from IP range 45.134.0.0/16",
            "2026-02-26T10:00:03Z WARN  frontend-api User-Agent pattern: 'Mozilla/5.0 (compatible; ScrapeBot/2.1)'",
            "2026-02-26T10:00:10Z WARN  frontend-api Rate limiter triggered for 1200 IPs",
            "2026-02-26T10:01:00Z ERROR frontend-api Connection queue full, dropping requests",
        ],
        "mock_deploys": [],
        "mock_k8s": {
            "pods": "4/4 Running (HPA scaling to 10)",
            "restarts": 0,
            "events": "HPA scaling 4->10, CPU pressure detected",
            "resource_pressure": True,
        },
    },

    "nginx-cache-flush": {
        "name": "Nginx Cache Stale — Auto-Resolve Demo",
        "pagerduty": {
            "id": "P1111111",
            "title": "nginx-cache: cache hit rate dropped to 12% (normal >85%)",
            "description": "nginx-cache cache hit rate fell from 88% to 12% at 08:42 UTC. Origin request rate 4x normal. P99 latency increased from 80ms to 310ms. Suspected stale cache after last deploy invalidated all keys.",
            "urgency": "high",
            "service": {"name": "nginx-cache", "id": "PSVC006"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.1, "after": 0.8, "unit": "%"},
            "request_rate": {"before": 5000, "after": 5100, "unit": "req/s"},
            "latency_p99": {"before": 0.08, "after": 0.31, "unit": "s"},
            "cpu_percent": {"before": 15, "after": 62, "unit": "%"},
            "memory_mb": {"before": 400, "after": 410, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-03-03T08:42:01Z WARN  nginx-cache cache MISS ratio 88% (last 5m)",
            "2026-03-03T08:42:01Z INFO  nginx-cache origin upstream requests: 4x normal",
            "2026-03-03T08:42:02Z WARN  nginx-cache /var/cache/nginx stale entries detected post-deploy",
            "2026-03-03T08:42:10Z INFO  nginx-cache disk usage: 94% on /var/cache/nginx",
            "2026-03-03T08:42:15Z INFO  nginx-cache all pods Running, no OOMKill events",
        ],
        "mock_deploys": [
            {
                "pr": 212,
                "title": "bump cache key prefix to v3 (breaks v2 cache, intentional)",
                "author": "deploy-bot",
                "merged_at": "2026-03-03T08:40:00Z",
                "files_changed": ["nginx.conf"],
                "diff_preview": "- proxy_cache_key \"v2:$host$request_uri\";\n+ proxy_cache_key \"v3:$host$request_uri\";",
            }
        ],
        "mock_k8s": {
            "pods": "2/2 Running",
            "restarts": 0,
            "events": "No unusual events",
            "resource_pressure": False,
        },
    },
    "ec2-nginx-down": {
        "name": "EC2 Nginx Service Down — Requires Approval to Restart",
        "pagerduty": {
            "id": "P9999991",
            "title": "EC2 nginx service not responding — health check failing",
            "description": "HTTP health check on 3.249.183.159 returning connection refused. Nginx process appears to have crashed. Last successful check 4 minutes ago. CloudWatch StatusCheckFailed=0 (instance is up), application-level failure only.",
            "urgency": "high",
            "service": {"name": "3.249.183.159", "id": "PSVC009"},
        },
        "mock_metrics": {
            "error_rate": {"before": 0.1, "after": 100.0, "unit": "%"},
            "request_rate": {"before": 120, "after": 0, "unit": "req/s"},
            "latency_p99": {"before": 0.05, "after": 30.0, "unit": "s"},
            "cpu_percent": {"before": 12, "after": 8, "unit": "%"},
            "memory_mb": {"before": 180, "after": 175, "unit": "MB"},
            "pod_restarts": {"before": 0, "after": 0, "unit": ""},
        },
        "mock_logs": [
            "2026-03-04T18:00:01Z ERROR nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)",
            "2026-03-04T18:00:01Z ERROR nginx: configuration file /etc/nginx/nginx.conf test failed",
            "2026-03-04T18:00:02Z WARN  healthcheck: GET http://3.249.183.159/ — connection refused",
            "2026-03-04T18:00:10Z WARN  healthcheck: GET http://3.249.183.159/ — connection refused (retry 2/3)",
            "2026-03-04T18:00:20Z ERROR healthcheck: service unreachable after 3 retries — alerting",
        ],
        "mock_deploys": [],
        "mock_k8s": {
            "pods": "N/A — EC2 workload",
            "restarts": 0,
            "events": "EC2 instance running, nginx process down",
            "resource_pressure": False,
        },
    },
}


def send_alert(scenario_name: str):
    """Send a mock incident to Pagemenot."""
    if scenario_name == "--list":
        print("Available scenarios:\n")
        for name, s in SCENARIOS.items():
            print(f"  {name:25s} — {s['name']}")
        print(f"\n  --random                    — Pick a random scenario")
        print("\nSource flags (test webhook parsing without real accounts):")
        print("  --source pagerduty          (default)")
        print("  --source opsgenie")
        print("  --source datadog")
        print("  --source newrelic")
        print("  --source alertmanager")
        return

    if scenario_name == "--random":
        scenario_name = random.choice(list(SCENARIOS.keys()))
        print(f"Randomly selected: {scenario_name}")

    scenario = SCENARIOS.get(scenario_name)
    if not scenario:
        print(f"Unknown scenario: {scenario_name}")
        print(f"Available: {', '.join(SCENARIOS.keys())}")
        sys.exit(1)

    source = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--source" else "pagerduty"
    pd = scenario["pagerduty"]
    service = pd["service"]["name"]

    payloads = {
        "pagerduty": (
            "/webhooks/pagerduty",
            {"messages": [{"event": "incident.triggered", "incident": {
                **pd,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "assignments": [{"summary": "oncall-sre"}],
                "status": "triggered",
            }}]},
        ),
        "opsgenie": (
            "/webhooks/opsgenie",
            {"action": "Create", "alert": {
                "alertId": pd["id"],
                "message": pd["title"],
                "entity": service,
                "priority": "P1" if pd["urgency"] == "high" else "P3",
                "description": pd.get("description", ""),
            }},
        ),
        "datadog": (
            "/webhooks/datadog",
            {
                "title": pd["title"],
                "alert_type": "error",
                "body": pd.get("description", ""),
                "tags": {"service": service},
                "id": pd["id"],
            },
        ),
        "newrelic": (
            "/webhooks/newrelic",
            {
                "condition_name": pd["title"],
                "severity": "CRITICAL" if pd["urgency"] == "high" else "WARNING",
                "details": pd.get("description", ""),
                "targets": [{"name": service}],
                "incident_id": pd["id"],
            },
        ),
        "alertmanager": (
            "/webhooks/alertmanager",
            {"alerts": [{"status": "firing", "labels": {
                "alertname": pd["title"],
                "service": service,
                "severity": "critical" if pd["urgency"] == "high" else "warning",
            }, "annotations": {"description": pd.get("description", "")}}]},
        ),
    }

    if source not in payloads:
        print(f"Unknown source: {source}. Use: {', '.join(payloads)}")
        sys.exit(1)

    path, payload = payloads[source]
    print(f"Firing [{source}] {scenario['name']}")
    print(f"  Service: {service}")
    print(f"  → POST {PAGEMENOT_URL}{path}")

    try:
        body = json.dumps(payload).encode()
        resp = httpx.post(
            f"{PAGEMENOT_URL}{path}",
            content=body,
            headers={"Content-Type": "application/json", **_sign(source, body)},
            timeout=5.0,
        )
        print(f"\nAccepted ({resp.status_code}) — check Slack")
    except httpx.ConnectError:
        print(f"\nCannot reach Pagemenot at {PAGEMENOT_URL}")
        print("Run: docker compose up -d")
        sys.exit(1)


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "--list"
    send_alert(name)
