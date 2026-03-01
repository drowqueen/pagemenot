#!/usr/bin/env bash
# Pagemenot setup wizard — generates .env interactively.
# Run once, then: make install
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[0;33m'; GREEN='\033[0;32m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
say()  { echo -e "$*"; }
ok()   { say "${GREEN}✓ $*${RESET}"; }
warn() { say "${YELLOW}⚠ $*${RESET}"; }
err()  { say "${RED}✗ $*${RESET}"; }
header() { say "\n${BOLD}── $* ─────────────────────────────────────────${RESET}"; }

prompt() {
    # prompt <var> <label> [default]
    local var=$1 label=$2 default=${3:-}
    local hint; hint=$( [[ -n "$default" ]] && echo " [${DIM}${default}${RESET}]" || echo "" )
    printf "%b%s%b%s: " "${YELLOW}" "$label" "${RESET}" "$hint"
    read -r input
    if [[ -z "$input" && -n "$default" ]]; then input="$default"; fi
    eval "$var=\"\$input\""
}

prompt_secret() {
    # prompt_secret <var> <label>
    local var=$1 label=$2
    printf "%b%s%b: " "${YELLOW}" "$label" "${RESET}"
    read -rs input; echo
    eval "$var=\"\$input\""
}

ask_yes() {
    # ask_yes <question> → returns 0 (yes) or 1 (no)
    printf "%b%s%b [y/N]: " "${YELLOW}" "$1" "${RESET}"
    read -r yn
    [[ "${yn,,}" == "y" ]]
}

ping_url() {
    curl -sf --max-time 5 "$1" > /dev/null 2>&1
}

mask() {
    local s=$1
    [[ -z "$s" ]] && echo "(not set)" && return
    echo "${s:0:4}$(printf '*%.0s' $(seq 1 $((${#s} - 4 < 0 ? 0 : ${#s} - 4))))"
}

write_env() {
    local file=$1; shift
    # Args: KEY=VALUE pairs
    : > "$file"
    for pair in "$@"; do
        echo "$pair" >> "$file"
    done
}

# ── Existing .env ─────────────────────────────────────────────────────────────
say "${BOLD}Pagemenot setup wizard${RESET}"
say "${DIM}Generates .env from your answers. Run once, then: make install${RESET}"

if [[ -f .env ]]; then
    warn ".env already exists."
    if ! ask_yes "Reconfigure? (existing .env will be backed up)"; then
        say "No changes made. Run ${BOLD}make install${RESET} to start."
        exit 0
    fi
    backup=".env.bak.$(date +%s)"
    cp .env "$backup"
    ok "Backed up to $backup"
fi

# ── Slack (required) ──────────────────────────────────────────────────────────
header "Slack (required)"
say "${DIM}api.slack.com/apps → your app → OAuth & Basic Information${RESET}"
prompt_secret SLACK_BOT_TOKEN  "Bot Token (xoxb-...)"
prompt_secret SLACK_APP_TOKEN  "App Token (xapp-...)"
prompt PAGEMENOT_CHANNEL "Results channel (no #)" "incidents"

# ── LLM ───────────────────────────────────────────────────────────────────────
header "LLM provider"
say "  1) Ollama (self-hosted — recommended for production)"
say "  2) OpenAI"
say "  3) Anthropic"
say "  4) Gemini"
prompt LLM_CHOICE "Choice" "1"

LLM_PROVIDER="" LLM_MODEL="" OLLAMA_URL="" OPENAI_API_KEY="" ANTHROPIC_API_KEY=""
GEMINI_API_KEY="" LLM_EXTERNAL_ENTERPRISE_CONFIRMED="false"

case "$LLM_CHOICE" in
1)
    LLM_PROVIDER="ollama"
    prompt OLLAMA_URL "Ollama URL" "http://localhost:11434"
    prompt LLM_MODEL  "Model" "llama3.1"
    if ping_url "$OLLAMA_URL"; then ok "Ollama reachable"; else warn "Ollama not reachable — continue anyway"; fi
    ;;
2|3|4)
    say "${RED}External LLMs send metrics, logs, and PR diffs outside your network.${RESET}"
    say "Only use if you have a signed zero-retention DPA with your provider."
    if ! ask_yes "Confirm enterprise approval for external LLM"; then
        err "External LLM not confirmed. Re-run and choose Ollama, or confirm approval."
        exit 1
    fi
    LLM_EXTERNAL_ENTERPRISE_CONFIRMED="true"
    case "$LLM_CHOICE" in
    2) LLM_PROVIDER="openai";    prompt LLM_MODEL "Model" "gpt-4o";               prompt_secret OPENAI_API_KEY    "OpenAI API key" ;;
    3) LLM_PROVIDER="anthropic"; prompt LLM_MODEL "Model" "claude-sonnet-4-6";    prompt_secret ANTHROPIC_API_KEY "Anthropic API key" ;;
    4) LLM_PROVIDER="gemini";    prompt LLM_MODEL "Model" "gemini-2.0-flash";      prompt_secret GEMINI_API_KEY    "Gemini API key" ;;
    esac
    ;;
*)
    err "Invalid choice"; exit 1 ;;
esac

# ── Optional integrations ─────────────────────────────────────────────────────
PROMETHEUS_URL="" PROMETHEUS_AUTH_TOKEN=""
GRAFANA_URL="" GRAFANA_API_KEY="" GRAFANA_ORG_ID=""
LOKI_URL="" LOKI_AUTH_TOKEN="" LOKI_ORG_ID=""
DATADOG_API_KEY="" DATADOG_APP_KEY="" DATADOG_SITE="datadoghq.com"
NEWRELIC_API_KEY="" NEWRELIC_ACCOUNT_ID=""
PAGERDUTY_API_KEY="" PAGERDUTY_FROM_EMAIL=""
GITHUB_TOKEN="" GITHUB_ORG=""
JIRA_SM_URL="" JIRA_SM_EMAIL="" JIRA_SM_API_TOKEN="" JIRA_SM_PROJECT_KEY=""
KUBECONFIG_PATH=""
AWS_ROLE_ARN="" AWS_REGION="us-east-1"
GOOGLE_APPLICATION_CREDENTIALS=""

header "Optional integrations (Enter to skip each)"

if ask_yes "Prometheus"; then
    prompt PROMETHEUS_URL "Prometheus URL" "http://prometheus:9090"
    prompt PROMETHEUS_AUTH_TOKEN "Auth token (managed Prometheus, else blank)" ""
    ping_url "$PROMETHEUS_URL" && ok "Prometheus reachable" || warn "Not reachable — check URL later"
fi

if ask_yes "Grafana"; then
    prompt GRAFANA_URL "Grafana URL" "http://grafana:3000"
    prompt_secret GRAFANA_API_KEY "Grafana API key"
    prompt GRAFANA_ORG_ID "Org ID (Grafana Cloud only, else blank)" ""
    ping_url "$GRAFANA_URL" && ok "Grafana reachable" || warn "Not reachable — check URL later"
fi

if ask_yes "Loki"; then
    prompt LOKI_URL "Loki URL" "http://loki:3100"
    prompt LOKI_AUTH_TOKEN "Auth token (Grafana Cloud, else blank)" ""
    prompt LOKI_ORG_ID "Org ID (multi-tenant Loki, else blank)" ""
fi

if ask_yes "Datadog"; then
    prompt_secret DATADOG_API_KEY "Datadog API key"
    prompt_secret DATADOG_APP_KEY "Datadog App key"
    prompt DATADOG_SITE "Datadog site" "datadoghq.com"
fi

if ask_yes "New Relic"; then
    prompt_secret NEWRELIC_API_KEY "New Relic API key (NRAK-...)"
    prompt NEWRELIC_ACCOUNT_ID "Account ID" ""
fi

if ask_yes "PagerDuty"; then
    prompt_secret PAGERDUTY_API_KEY "PagerDuty REST API key"
    prompt PAGERDUTY_FROM_EMAIL "Requester email (PagerDuty account email)" ""
fi

if ask_yes "GitHub (deploy correlation)"; then
    prompt_secret GITHUB_TOKEN "GitHub token (repo read scope)"
    prompt GITHUB_ORG "GitHub org" ""
fi

if ask_yes "Jira Service Management"; then
    prompt JIRA_SM_URL       "Jira URL (https://<workspace>.atlassian.net)" ""
    prompt JIRA_SM_EMAIL     "Jira account email" ""
    prompt_secret JIRA_SM_API_TOKEN "Jira API token"
    prompt JIRA_SM_PROJECT_KEY "Project key (e.g. OPS)" ""
fi

if ask_yes "Kubernetes (runbook execution)"; then
    prompt KUBECONFIG_PATH "Kubeconfig path inside container" "/app/kubeconfig"
fi

if ask_yes "AWS (SSM / ECS execution)"; then
    prompt AWS_ROLE_ARN "IAM role ARN" "arn:aws:iam::ACCOUNT:role/pagemenot-exec"
    prompt AWS_REGION   "Region" "us-east-1"
fi

if ask_yes "GCP (Cloud Logging / Monitoring)"; then
    prompt GOOGLE_APPLICATION_CREDENTIALS "Service account JSON path" "/path/to/pagemenot-sa.json"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
header "Summary"
say "  Slack bot token   : $(mask "$SLACK_BOT_TOKEN")"
say "  Slack app token   : $(mask "$SLACK_APP_TOKEN")"
say "  Channel           : $PAGEMENOT_CHANNEL"
say "  LLM               : $LLM_PROVIDER / $LLM_MODEL"
[[ -n "$PROMETHEUS_URL" ]] && say "  Prometheus        : $PROMETHEUS_URL"
[[ -n "$GRAFANA_URL"    ]] && say "  Grafana           : $GRAFANA_URL"
[[ -n "$LOKI_URL"       ]] && say "  Loki              : $LOKI_URL"
[[ -n "$DATADOG_API_KEY" ]] && say "  Datadog           : $DATADOG_SITE"
[[ -n "$NEWRELIC_API_KEY" ]] && say "  New Relic         : account $NEWRELIC_ACCOUNT_ID"
[[ -n "$PAGERDUTY_API_KEY" ]] && say "  PagerDuty         : $(mask "$PAGERDUTY_API_KEY")"
[[ -n "$GITHUB_TOKEN"   ]] && say "  GitHub            : org=$GITHUB_ORG"
[[ -n "$JIRA_SM_URL"    ]] && say "  Jira SM           : $JIRA_SM_URL"
[[ -n "$KUBECONFIG_PATH" ]] && say "  Kubernetes        : $KUBECONFIG_PATH"
[[ -n "$AWS_ROLE_ARN"   ]] && say "  AWS               : $AWS_ROLE_ARN"
[[ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]] && say "  GCP               : $GOOGLE_APPLICATION_CREDENTIALS"

say ""
if ! ask_yes "Write .env and continue"; then
    say "Aborted — no changes written."
    exit 0
fi

# ── Write .env ────────────────────────────────────────────────────────────────
{
echo "# Generated by setup.sh on $(date -u '+%Y-%m-%d %H:%M UTC')"
echo ""
echo "# ── Slack ──────────────────────────────────────────────────────────────"
echo "SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN"
echo "SLACK_APP_TOKEN=$SLACK_APP_TOKEN"
echo "PAGEMENOT_CHANNEL=$PAGEMENOT_CHANNEL"
echo ""
echo "# ── LLM ────────────────────────────────────────────────────────────────"
echo "LLM_PROVIDER=$LLM_PROVIDER"
echo "LLM_MODEL=$LLM_MODEL"
[[ -n "$OLLAMA_URL"       ]] && echo "OLLAMA_URL=$OLLAMA_URL"
[[ -n "$OPENAI_API_KEY"   ]] && echo "OPENAI_API_KEY=$OPENAI_API_KEY"
[[ -n "$ANTHROPIC_API_KEY" ]] && echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
[[ -n "$GEMINI_API_KEY"   ]] && echo "GEMINI_API_KEY=$GEMINI_API_KEY"
[[ "$LLM_EXTERNAL_ENTERPRISE_CONFIRMED" == "true" ]] && echo "LLM_EXTERNAL_ENTERPRISE_CONFIRMED=true"
echo ""
echo "# ── Integrations ───────────────────────────────────────────────────────"
[[ -n "$PROMETHEUS_URL"   ]] && echo "PROMETHEUS_URL=$PROMETHEUS_URL"
[[ -n "$PROMETHEUS_AUTH_TOKEN" ]] && echo "PROMETHEUS_AUTH_TOKEN=$PROMETHEUS_AUTH_TOKEN"
[[ -n "$GRAFANA_URL"      ]] && echo "GRAFANA_URL=$GRAFANA_URL"
[[ -n "$GRAFANA_API_KEY"  ]] && echo "GRAFANA_API_KEY=$GRAFANA_API_KEY"
[[ -n "$GRAFANA_ORG_ID"   ]] && echo "GRAFANA_ORG_ID=$GRAFANA_ORG_ID"
[[ -n "$LOKI_URL"         ]] && echo "LOKI_URL=$LOKI_URL"
[[ -n "$LOKI_AUTH_TOKEN"  ]] && echo "LOKI_AUTH_TOKEN=$LOKI_AUTH_TOKEN"
[[ -n "$LOKI_ORG_ID"      ]] && echo "LOKI_ORG_ID=$LOKI_ORG_ID"
[[ -n "$DATADOG_API_KEY"  ]] && echo "DATADOG_API_KEY=$DATADOG_API_KEY"
[[ -n "$DATADOG_APP_KEY"  ]] && echo "DATADOG_APP_KEY=$DATADOG_APP_KEY"
[[ -n "$DATADOG_SITE"     && "$DATADOG_SITE" != "datadoghq.com" ]] && echo "DATADOG_SITE=$DATADOG_SITE"
[[ -n "$NEWRELIC_API_KEY" ]] && echo "NEWRELIC_API_KEY=$NEWRELIC_API_KEY"
[[ -n "$NEWRELIC_ACCOUNT_ID" ]] && echo "NEWRELIC_ACCOUNT_ID=$NEWRELIC_ACCOUNT_ID"
[[ -n "$PAGERDUTY_API_KEY" ]] && echo "PAGERDUTY_API_KEY=$PAGERDUTY_API_KEY"
[[ -n "$PAGERDUTY_FROM_EMAIL" ]] && echo "PAGERDUTY_FROM_EMAIL=$PAGERDUTY_FROM_EMAIL"
[[ -n "$GITHUB_TOKEN"     ]] && echo "GITHUB_TOKEN=$GITHUB_TOKEN"
[[ -n "$GITHUB_ORG"       ]] && echo "GITHUB_ORG=$GITHUB_ORG"
[[ -n "$JIRA_SM_URL"      ]] && echo "JIRA_SM_URL=$JIRA_SM_URL"
[[ -n "$JIRA_SM_EMAIL"    ]] && echo "JIRA_SM_EMAIL=$JIRA_SM_EMAIL"
[[ -n "$JIRA_SM_API_TOKEN" ]] && echo "JIRA_SM_API_TOKEN=$JIRA_SM_API_TOKEN"
[[ -n "$JIRA_SM_PROJECT_KEY" ]] && echo "JIRA_SM_PROJECT_KEY=$JIRA_SM_PROJECT_KEY"
[[ -n "$KUBECONFIG_PATH"  ]] && echo "KUBECONFIG_PATH=$KUBECONFIG_PATH"
[[ -n "$AWS_ROLE_ARN"     ]] && echo "AWS_ROLE_ARN=$AWS_ROLE_ARN"
[[ -n "$AWS_REGION" && "$AWS_REGION" != "us-east-1" ]] && echo "AWS_REGION=$AWS_REGION"
[[ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]] && echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
echo ""
echo "LOG_LEVEL=INFO"
} > .env

chmod 600 .env
ok ".env written (chmod 600)"

# ── services.yaml reminder ────────────────────────────────────────────────────
if [[ -n "$GITHUB_TOKEN" ]]; then
    say ""
    say "${BOLD}Service → repo mapping${RESET}"
    say "Edit ${BOLD}config/services.yaml${RESET} to map service names to GitHub repos."
    say "Required when repo names differ from service names or you use a monorepo."
    say "See the file for annotated examples. Skip if repo names match service names."
fi

say ""
say "${BOLD}Next step:${RESET} ${GREEN}make install${RESET}"
