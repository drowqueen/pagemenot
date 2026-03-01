"""Pagemenot configuration — all from environment variables."""

from pydantic_settings import BaseSettings
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

    # ── Vector store (embedded ChromaDB) ──────────────────
    chroma_path: str = "/app/data/chroma"

    # ── Slack ─────────────────────────────────────────────
    pagemenot_channel: str = "incidents"           # channel where results are posted
    pagemenot_alert_channels: str = "alerts,incidents"  # channels to passively monitor (comma-separated)
    pagemenot_enable_channel_monitor: bool = True  # auto-triage alert-looking messages in watched channels
    pagemenot_enable_mentions: bool = True         # respond to @Pagemenot mentions
    pagemenot_enable_slash_command: bool = True    # respond to /pagemenot triage
    pagemenot_enable_webhooks: bool = True         # receive webhook POSTs from external tools

    # ── Optional integrations ─────────────────────────────
    # Metrics / dashboards
    prometheus_url: Optional[str] = None
    prometheus_auth_token: Optional[str] = None
    grafana_url: Optional[str] = None
    grafana_api_key: Optional[str] = None
    grafana_org_id: Optional[str] = None   # required for Grafana Cloud
    loki_url: Optional[str] = None
    loki_auth_token: Optional[str] = None
    loki_org_id: Optional[str] = None      # required for Grafana Cloud / multi-tenant Loki
    datadog_api_key: Optional[str] = None
    datadog_app_key: Optional[str] = None
    datadog_site: str = "datadoghq.com"
    newrelic_api_key: Optional[str] = None
    newrelic_account_id: Optional[str] = None
    # Alerting / on-call
    pagerduty_api_key: Optional[str] = None
    opsgenie_api_key: Optional[str] = None
    # Jira Service Management
    jira_sm_url: Optional[str] = None
    jira_sm_email: Optional[str] = None
    jira_sm_api_token: Optional[str] = None
    jira_sm_project_key: Optional[str] = None
    jira_sm_issue_type: str = "Service Request"  # fallback, not used when service desk API is available
    jira_sm_service_desk_id: Optional[str] = None   # auto-discovered if not set
    jira_sm_request_type_id: Optional[str] = None   # auto-discovered if not set
    # Source control / deploys
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    # Execution
    kubeconfig_path: Optional[str] = None
    pagemenot_exec_namespace: str = "production"  # default k8s namespace for runbook {{ namespace }}
    pagemenot_exec_enabled: bool = True         # master switch for autonomous execution
    pagemenot_exec_dry_run: bool = True         # dry run by default — set false for real execution
    pagemenot_oncall_channel: Optional[str] = None  # channel to ping on critical escalations
    pagemenot_autoapprove_delay: int = 900      # seconds before auto-executing [AUTO-SAFE] steps
    pagemenot_dedup_ttl_short: int = 600        # dedup window for critical/high (seconds)
    pagemenot_dedup_ttl_long: int = 1800        # dedup window for medium/low (seconds)
    # Webhook HMAC secrets (optional — skip verification if not set, warn at startup)
    webhook_secret_pagerduty: Optional[str] = None
    webhook_secret_grafana: Optional[str] = None
    webhook_secret_alertmanager: Optional[str] = None
    webhook_secret_datadog: Optional[str] = None
    webhook_secret_opsgenie: Optional[str] = None
    webhook_secret_newrelic: Optional[str] = None
    webhook_secret_generic: Optional[str] = None

    # External LLM compliance gate
    llm_external_enterprise_confirmed: bool = False  # must be true to use non-Ollama LLMs
    # AWS execution role
    aws_role_arn: Optional[str] = None          # IAM role pagemenot assumes for AWS ops
    aws_region: str = "us-east-1"

    log_level: str = "INFO"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
