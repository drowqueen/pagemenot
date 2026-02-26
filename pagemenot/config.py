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
    # Source control / deploys
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    # Execution
    kubeconfig_path: Optional[str] = None

    log_level: str = "INFO"

    @property
    def crewai_llm_string(self) -> str:
        """Return CrewAI-compatible LLM string."""
        if self.llm_provider == "openai":
            return f"openai/{self.llm_model}"
        elif self.llm_provider == "anthropic":
            return f"anthropic/{self.llm_model}"
        elif self.llm_provider == "ollama":
            return f"ollama/{self.llm_model}"
        return self.llm_model

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
