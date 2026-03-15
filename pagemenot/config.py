"""Pagemenot configuration — all from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import Optional


class Settings(BaseSettings):
    # ── Required ──────────────────────────────────────────
    slack_bot_token: str
    slack_app_token: str

    # ── LLM ───────────────────────────────────────────────
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_embedding_model: Optional[str] = (
        None  # e.g. nomic-embed-text — enables cross-incident memory with Ollama
    )

    # ── Postmortem LLM (optional — falls back to llm_provider/llm_model) ──
    postmortem_llm_provider: Optional[str] = (
        None  # e.g. anthropic — used only for postmortem drafting
    )
    postmortem_llm_model: Optional[str] = None  # e.g. claude-opus-4-6

    # ── Vector store ──────────────────────────────────────
    chroma_path: str = "/app/data/chroma"  # used only when CHROMA_HOST is not set (embedded mode)
    chroma_host: Optional[str] = None  # remote ChromaDB server host (required for multi-replica)
    chroma_port: int = 8000  # remote ChromaDB server port

    # ── Slack ─────────────────────────────────────────────
    pagemenot_channel: str = "incidents"  # channel where results are posted
    pagemenot_alert_channels: str = (
        "alerts,incidents"  # channels to passively monitor (comma-separated)
    )
    pagemenot_enable_channel_monitor: bool = (
        True  # auto-triage alert-looking messages in watched channels
    )
    pagemenot_enable_mentions: bool = True  # respond to @Pagemenot mentions
    pagemenot_enable_slash_command: bool = True  # respond to /pagemenot triage
    pagemenot_enable_webhooks: bool = True  # receive webhook POSTs from external tools

    # ── Optional integrations ─────────────────────────────
    # Metrics / dashboards
    prometheus_url: Optional[str] = None
    prometheus_auth_token: Optional[str] = None
    grafana_url: Optional[str] = None
    grafana_api_key: Optional[str] = None
    grafana_org_id: Optional[str] = None  # required for Grafana Cloud
    loki_url: Optional[str] = None
    loki_auth_token: Optional[str] = None
    loki_org_id: Optional[str] = None  # required for Grafana Cloud / multi-tenant Loki
    datadog_api_key: Optional[str] = None
    datadog_app_key: Optional[str] = None
    datadog_site: str = "datadoghq.com"
    newrelic_api_key: Optional[str] = None
    newrelic_account_id: Optional[str] = None
    # Alerting / on-call
    pagerduty_api_key: Optional[str] = None
    pagerduty_from_email: Optional[str] = (
        None  # requester email for PD API; auto-discovered if unset
    )
    opsgenie_api_key: Optional[str] = None
    # Jira Service Management
    jira_sm_url: Optional[str] = None
    jira_sm_email: Optional[str] = None
    jira_sm_api_token: Optional[str] = None
    jira_sm_project_key: Optional[str] = None
    jira_sm_issue_type: str = (
        "Service Request"  # fallback, not used when service desk API is available
    )
    jira_sm_service_desk_id: Optional[str] = None  # auto-discovered if not set
    jira_sm_request_type_id: Optional[str] = None  # auto-discovered if not set
    jira_done_statuses: str = (
        "done,resolved,closed,complete,fixed"  # comma-separated, case-insensitive
    )
    # Source control / deploys
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    # Execution
    kubeconfig_path: Optional[str] = None
    pagemenot_exec_namespace: str = "default"  # fallback k8s namespace for runbook {{ namespace }}
    pagemenot_service_namespaces: str = (
        ""  # per-service overrides: "payment-service=payments,checkout-service=checkout"
    )
    pagemenot_webhook_rate_limit: str = (
        "60/minute"  # slowapi rate limit string for all webhook endpoints
    )
    pagemenot_exec_enabled: bool = True  # master switch for autonomous execution
    pagemenot_exec_dry_run: bool = True  # true = simulate; false = real execution
    pagemenot_oncall_channel: Optional[str] = None  # channel to ping on critical escalations
    pagemenot_autoapprove_delay: int = 900  # seconds before auto-executing [AUTO-SAFE] steps
    pagemenot_state_bucket: Optional[str] = (
        None  # gs://bucket, s3://bucket, or az://container for state persistence
    )
    pagemenot_runbook_bucket: str = ""  # bucket to sync runbooks from at startup: gs://bucket/path, s3://bucket/path, or az://account/container
    pagemenot_dedup_ttl_short: int = 86400  # dedup window for critical/high (seconds) — 24h
    pagemenot_dedup_ttl_long: int = 86400  # dedup window for medium/low (seconds) — 24h
    # Severity thresholds — controls when each action triggers
    pagemenot_jira_min_severity: str = "low"  # open Jira ticket: low/medium/high/critical
    pagemenot_pd_min_severity: str = "high"  # page PD/escalate: low/medium/high/critical
    pagemenot_approval_min_severity: str = (
        "high"  # require human approval for risky commands: low/medium/high/critical
    )
    # Approval state store
    redis_url: Optional[str] = (
        None  # e.g. redis://localhost:6379/0 — for approval state persistence across restarts
    )

    # Webhook HMAC secrets (optional — skip verification if not set, warn at startup)
    webhook_secret_pagerduty: Optional[str] = None
    webhook_secret_grafana: Optional[str] = None
    webhook_secret_alertmanager: Optional[str] = None
    webhook_secret_datadog: Optional[str] = None
    webhook_secret_opsgenie: Optional[str] = None
    webhook_secret_newrelic: Optional[str] = None
    webhook_secret_generic: Optional[str] = None
    webhook_secret_jira: Optional[str] = None
    webhook_secret_azure: Optional[str] = None

    # External LLM compliance gate
    llm_external_enterprise_confirmed: bool = False  # must be true to use non-Ollama LLMs
    # Cloud execution credentials
    aws_role_arn: Optional[str] = (
        None  # IAM role pagemenot assumes for AWS ops (single-account fallback)
    )
    aws_accounts: dict[str, str] = {}  # account_id → role_arn; per-account override of aws_role_arn
    aws_region: Optional[str] = None  # default region; per-alert region takes precedence
    google_application_credentials: Optional[str] = None  # path to GCP service account JSON
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    azure_subscription_id: Optional[str] = None
    azure_resource_group: Optional[str] = None  # resource group for az CLI exec steps

    pagemenot_dedup_short_ttl_severities: str = (
        "critical,high"  # severities that use dedup_ttl_short
    )
    pagemenot_http_timeout: int = 10  # seconds for all httpx calls
    pagemenot_subprocess_timeout: int = 30  # seconds for kubectl/aws/shell exec
    pagemenot_az_timeout: int = 660  # seconds for az write/wait commands — must exceed az --timeout value used in runbooks (e.g. flexible-server wait --timeout 600 needs >600s here)
    pagemenot_az_read_timeout: int = 30  # seconds for read-only az show/list commands
    pagemenot_slack_chunk_size: int = 2900  # chars per Slack message block
    pagemenot_slack_max_chunks: int = 3  # max blocks posted per triage result
    pagemenot_approval_ttl: int = 3600  # seconds before an approval entry expires
    pagemenot_verify_timeout: int = 300  # seconds to poll CW alarm for recovery after runbook exec
    pagemenot_verify_poll_interval: int = 15  # CW alarm polling cadence (seconds)
    pagemenot_rag_incidents_n_results: int = 5  # past incidents returned by RAG
    pagemenot_rag_runbooks_n_results: int = 1  # runbooks returned by RAG — best match only
    # Extra cloud provider label aliases merged into built-in normalization map.
    # JSON dict: {"ovh": "ovh", "digitalocean": "onprem", "my-bare-metal": "onprem"}
    # Keys are raw label values from alert sources; values are normalized provider names.
    # These names are also used as cloud_provider metadata in ChromaDB — tag runbooks accordingly.
    pagemenot_cloud_provider_aliases: dict[str, str] = {}
    # Fallback when an alert source carries no cloud_provider label at all.
    # Leave empty to keep current behaviour (no filter, searches all runbooks).
    # Pure on-prem deployments: set to "onprem". Hetzner-only: "hetzner".
    pagemenot_default_cloud_provider: str = ""
    chroma_incidents_collection: str = "incidents"  # ChromaDB collection name for postmortems
    chroma_runbooks_collection: str = "runbooks"  # ChromaDB collection name for runbooks

    pagemenot_ssl_keyfile: Optional[str] = None
    pagemenot_ssl_certfile: Optional[str] = None
    pagemenot_https_port: int = 8443

    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_ssl_config(self) -> "Settings":
        keyfile = self.pagemenot_ssl_keyfile
        certfile = self.pagemenot_ssl_certfile
        if (keyfile is None) != (certfile is None):
            raise ValueError(
                "PAGEMENOT_SSL_KEYFILE and PAGEMENOT_SSL_CERTFILE must be set together"
            )
        return self

    @property
    def enabled_integrations(self) -> list[str]:
        integrations = []
        if self.prometheus_url:
            integrations.append("prometheus")
        if self.grafana_url:
            integrations.append("grafana")
        if self.loki_url:
            integrations.append("loki")
        if self.datadog_api_key:
            integrations.append("datadog")
        if self.newrelic_api_key:
            integrations.append("newrelic")
        if self.pagerduty_api_key:
            integrations.append("pagerduty")
        if self.opsgenie_api_key:
            integrations.append("opsgenie")
        if self.github_token:
            integrations.append("github")
        if self.kubeconfig_path:
            integrations.append("kubernetes")
        return integrations

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
