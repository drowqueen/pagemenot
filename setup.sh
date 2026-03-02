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

# _REPLY holds the last prompt result (avoids eval)
_REPLY=""

prompt() {
    # prompt <label> [default]
    local label=$1 default=${2:-}
    local hint; hint=$( [[ -n "$default" ]] && echo " [${DIM}${default}${RESET}]" || echo "" )
    printf "%b%s%b%s: " "${YELLOW}" "$label" "${RESET}" "$hint"
    read -r _REPLY
    if [[ -z "$_REPLY" && -n "$default" ]]; then _REPLY="$default"; fi
}

prompt_secret() {
    # prompt_secret <label>
    local label=$1
    printf "%b%s%b (input hidden): " "${YELLOW}" "$label" "${RESET}"
    read -rs _REPLY; echo
}

ask_yes() {
    # ask_yes <question> → returns 0 (yes) or 1 (no)
    printf "%b%s%b [y/N]: " "${YELLOW}" "$1" "${RESET}"
    read -r _yn
    [[ "$(echo "$_yn" | tr '[:upper:]' '[:lower:]')" == "y" ]]
}

ping_url() {
    curl -sf --max-time 5 "$1" > /dev/null 2>&1
}

mask() {
    local s=$1
    [[ -z "$s" ]] && echo "(not set)" && return
    echo "${s:0:4}$(printf '*%.0s' $(seq 1 $((${#s} - 4 < 0 ? 0 : ${#s} - 4))))"
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
prompt_secret "Bot Token (xoxb-...)";  SLACK_BOT_TOKEN="$_REPLY"
prompt_secret "App Token (xapp-...)";  SLACK_APP_TOKEN="$_REPLY"
prompt "Results channel (no #)" "incidents"; PAGEMENOT_CHANNEL="$_REPLY"

# ── LLM ───────────────────────────────────────────────────────────────────────
header "LLM provider"
say "  1) Ollama (self-hosted — recommended for production)"
say "  2) OpenAI"
say "  3) Anthropic"
say "  4) Gemini"

LLM_PROVIDER="" LLM_MODEL="" OLLAMA_URL="" OLLAMA_EMBEDDING_MODEL="" OPENAI_API_KEY="" ANTHROPIC_API_KEY=""
GEMINI_API_KEY="" LLM_EXTERNAL_ENTERPRISE_CONFIRMED="false"

while true; do
    prompt "Choice" "1"; LLM_CHOICE="$_REPLY"
    case "$LLM_CHOICE" in
    1)
        LLM_PROVIDER="ollama"
        prompt "Ollama URL" "http://localhost:11434"; OLLAMA_URL="$_REPLY"
        prompt "Model" "llama3.1"; LLM_MODEL="$_REPLY"
        if ping_url "$OLLAMA_URL"; then ok "Ollama reachable"; else warn "Ollama not reachable — continue anyway"; fi
        say "${DIM}Cross-incident memory requires a local embedding model (ollama pull nomic-embed-text).${RESET}"
        prompt "Embedding model (blank to skip)" ""; OLLAMA_EMBEDDING_MODEL="$_REPLY"
        break
        ;;
    2|3|4)
        say "${RED}External LLMs send metrics, logs, and PR diffs outside your network.${RESET}"
        say "Only use if you have a signed zero-retention DPA with your provider."
        if ! ask_yes "Confirm enterprise approval for external LLM"; then
            warn "Unconfirmed. Choose a different provider or confirm approval."
            continue
        fi
        LLM_EXTERNAL_ENTERPRISE_CONFIRMED="true"
        case "$LLM_CHOICE" in
        2) LLM_PROVIDER="openai";    prompt "Model" "gpt-4o";            LLM_MODEL="$_REPLY"; prompt_secret "OpenAI API key";    OPENAI_API_KEY="$_REPLY" ;;
        3) LLM_PROVIDER="anthropic"; prompt "Model" "claude-sonnet-4-6"; LLM_MODEL="$_REPLY"; prompt_secret "Anthropic API key"; ANTHROPIC_API_KEY="$_REPLY" ;;
        4) LLM_PROVIDER="gemini";    prompt "Model" "gemini-2.0-flash";  LLM_MODEL="$_REPLY"; prompt_secret "Gemini API key";    GEMINI_API_KEY="$_REPLY" ;;
        esac
        break
        ;;
    *)
        err "Invalid choice — enter 1, 2, 3, or 4" ;;
    esac
done

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
    prompt "Prometheus URL" "http://prometheus:9090"; PROMETHEUS_URL="$_REPLY"
    prompt "Auth token (managed Prometheus, else blank)" ""; PROMETHEUS_AUTH_TOKEN="$_REPLY"
    ping_url "$PROMETHEUS_URL" && ok "Prometheus reachable" || warn "Not reachable — check URL later"
fi

if ask_yes "Grafana"; then
    prompt "Grafana URL" "http://grafana:3000"; GRAFANA_URL="$_REPLY"
    prompt_secret "Grafana API key"; GRAFANA_API_KEY="$_REPLY"
    prompt "Org ID (Grafana Cloud only, else blank)" ""; GRAFANA_ORG_ID="$_REPLY"
    ping_url "$GRAFANA_URL" && ok "Grafana reachable" || warn "Not reachable — check URL later"
fi

if ask_yes "Loki"; then
    prompt "Loki URL" "http://loki:3100"; LOKI_URL="$_REPLY"
    prompt "Auth token (Grafana Cloud, else blank)" ""; LOKI_AUTH_TOKEN="$_REPLY"
    prompt "Org ID (multi-tenant Loki, else blank)" ""; LOKI_ORG_ID="$_REPLY"
fi

if ask_yes "Datadog"; then
    prompt_secret "Datadog API key"; DATADOG_API_KEY="$_REPLY"
    prompt_secret "Datadog App key"; DATADOG_APP_KEY="$_REPLY"
    prompt "Datadog site" "datadoghq.com"; DATADOG_SITE="$_REPLY"
fi

if ask_yes "New Relic"; then
    prompt_secret "New Relic API key (NRAK-...)"; NEWRELIC_API_KEY="$_REPLY"
    prompt "Account ID" ""; NEWRELIC_ACCOUNT_ID="$_REPLY"
fi

if ask_yes "PagerDuty"; then
    prompt_secret "PagerDuty REST API key"; PAGERDUTY_API_KEY="$_REPLY"
    prompt "Requester email (PagerDuty account email)" ""; PAGERDUTY_FROM_EMAIL="$_REPLY"
fi

if ask_yes "GitHub (deploy correlation)"; then
    prompt_secret "GitHub token (repo read scope)"; GITHUB_TOKEN="$_REPLY"
    prompt "GitHub org" ""; GITHUB_ORG="$_REPLY"
fi

if ask_yes "Jira Service Management"; then
    prompt "Jira URL (https://<workspace>.atlassian.net)" ""; JIRA_SM_URL="$_REPLY"
    prompt "Jira account email" ""; JIRA_SM_EMAIL="$_REPLY"
    prompt_secret "Jira API token"; JIRA_SM_API_TOKEN="$_REPLY"
    prompt "Project key (e.g. OPS)" ""; JIRA_SM_PROJECT_KEY="$_REPLY"
fi

if ask_yes "Kubernetes (runbook execution)"; then
    prompt "Kubeconfig path inside container" "/app/kubeconfig"; KUBECONFIG_PATH="$_REPLY"
fi

if ask_yes "AWS (SSM / ECS execution)"; then
    prompt "IAM role ARN" "arn:aws:iam::ACCOUNT:role/pagemenot-exec"; AWS_ROLE_ARN="$_REPLY"
    prompt "Region" "us-east-1"; AWS_REGION="$_REPLY"
fi

if ask_yes "GCP (Cloud Logging / Monitoring)"; then
    prompt "Service account JSON path" "/path/to/pagemenot-sa.json"; GOOGLE_APPLICATION_CREDENTIALS="$_REPLY"
fi

# ── Image variant ─────────────────────────────────────────────────────────────
PAGEMENOT_BUILD_TARGET="base"

header "Container image variant"
say "  kubectl is always included. Select additional cloud CLIs to bake in."
say "  1) Kubernetes only  — kubectl                         (~1 GB)"
say "  2) AWS              — kubectl + AWS CLI v2            (+500 MB)"
say "  3) GCP              — kubectl + gcloud                (+400 MB)"
say "  4) Azure            — kubectl + Azure CLI             (+300 MB)"
say "  5) Multi-cloud      — kubectl + AWS CLI + gcloud + Azure CLI  (+1.2 GB)"

while true; do
    prompt "Choice" "1"; VARIANT_CHOICE="$_REPLY"
    case "$VARIANT_CHOICE" in
    1) PAGEMENOT_BUILD_TARGET="base";  ok "base  — kubectl only";              break ;;
    2) PAGEMENOT_BUILD_TARGET="aws";   ok "aws   — kubectl + AWS CLI v2";      break ;;
    3) PAGEMENOT_BUILD_TARGET="gcp";   ok "gcp   — kubectl + gcloud";          break ;;
    4) PAGEMENOT_BUILD_TARGET="azure"; ok "azure — kubectl + Azure CLI";        break ;;
    5) PAGEMENOT_BUILD_TARGET="cloud"; ok "cloud — kubectl + all three CLIs";  break ;;
    *) err "Enter 1–5" ;;
    esac
done

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
say "  Image variant     : $PAGEMENOT_BUILD_TARGET"

say ""
if ! ask_yes "Write .env and continue"; then
    say "Aborted — no changes written."
    exit 0
fi

# ── Write .env ────────────────────────────────────────────────────────────────
q() { echo "\"$1\""; }  # quote a value for .env

{
echo "# Generated by setup.sh on $(date -u '+%Y-%m-%d %H:%M UTC')"
echo ""
echo "# ── Slack ──────────────────────────────────────────────────────────────"
echo "SLACK_BOT_TOKEN=$(q "$SLACK_BOT_TOKEN")"
echo "SLACK_APP_TOKEN=$(q "$SLACK_APP_TOKEN")"
echo "PAGEMENOT_CHANNEL=$(q "$PAGEMENOT_CHANNEL")"
echo ""
echo "# ── LLM ────────────────────────────────────────────────────────────────"
echo "LLM_PROVIDER=$LLM_PROVIDER"
echo "LLM_MODEL=$LLM_MODEL"
[[ -n "$OLLAMA_URL"       ]] && echo "OLLAMA_URL=$(q "$OLLAMA_URL")"
[[ -n "$OLLAMA_EMBEDDING_MODEL" ]] && echo "OLLAMA_EMBEDDING_MODEL=$OLLAMA_EMBEDDING_MODEL"
[[ -n "$OPENAI_API_KEY"   ]] && echo "OPENAI_API_KEY=$(q "$OPENAI_API_KEY")"
[[ -n "$ANTHROPIC_API_KEY" ]] && echo "ANTHROPIC_API_KEY=$(q "$ANTHROPIC_API_KEY")"
[[ -n "$GEMINI_API_KEY"   ]] && echo "GEMINI_API_KEY=$(q "$GEMINI_API_KEY")"
echo "LLM_EXTERNAL_ENTERPRISE_CONFIRMED=$LLM_EXTERNAL_ENTERPRISE_CONFIRMED"
echo ""
echo "# ── Integrations ───────────────────────────────────────────────────────"
[[ -n "$PROMETHEUS_URL"   ]] && echo "PROMETHEUS_URL=$(q "$PROMETHEUS_URL")"
[[ -n "$PROMETHEUS_AUTH_TOKEN" ]] && echo "PROMETHEUS_AUTH_TOKEN=$(q "$PROMETHEUS_AUTH_TOKEN")"
[[ -n "$GRAFANA_URL"      ]] && echo "GRAFANA_URL=$(q "$GRAFANA_URL")"
[[ -n "$GRAFANA_API_KEY"  ]] && echo "GRAFANA_API_KEY=$(q "$GRAFANA_API_KEY")"
[[ -n "$GRAFANA_ORG_ID"   ]] && echo "GRAFANA_ORG_ID=$(q "$GRAFANA_ORG_ID")"
[[ -n "$LOKI_URL"         ]] && echo "LOKI_URL=$(q "$LOKI_URL")"
[[ -n "$LOKI_AUTH_TOKEN"  ]] && echo "LOKI_AUTH_TOKEN=$(q "$LOKI_AUTH_TOKEN")"
[[ -n "$LOKI_ORG_ID"      ]] && echo "LOKI_ORG_ID=$(q "$LOKI_ORG_ID")"
[[ -n "$DATADOG_API_KEY"  ]] && echo "DATADOG_API_KEY=$(q "$DATADOG_API_KEY")"
[[ -n "$DATADOG_APP_KEY"  ]] && echo "DATADOG_APP_KEY=$(q "$DATADOG_APP_KEY")"
[[ -n "$DATADOG_SITE"     && "$DATADOG_SITE" != "datadoghq.com" ]] && echo "DATADOG_SITE=$(q "$DATADOG_SITE")"
[[ -n "$NEWRELIC_API_KEY" ]] && echo "NEWRELIC_API_KEY=$(q "$NEWRELIC_API_KEY")"
[[ -n "$NEWRELIC_ACCOUNT_ID" ]] && echo "NEWRELIC_ACCOUNT_ID=$NEWRELIC_ACCOUNT_ID"
[[ -n "$PAGERDUTY_API_KEY" ]] && echo "PAGERDUTY_API_KEY=$(q "$PAGERDUTY_API_KEY")"
[[ -n "$PAGERDUTY_FROM_EMAIL" ]] && echo "PAGERDUTY_FROM_EMAIL=$(q "$PAGERDUTY_FROM_EMAIL")"
[[ -n "$GITHUB_TOKEN"     ]] && echo "GITHUB_TOKEN=$(q "$GITHUB_TOKEN")"
[[ -n "$GITHUB_ORG"       ]] && echo "GITHUB_ORG=$(q "$GITHUB_ORG")"
[[ -n "$JIRA_SM_URL"      ]] && echo "JIRA_SM_URL=$(q "$JIRA_SM_URL")"
[[ -n "$JIRA_SM_EMAIL"    ]] && echo "JIRA_SM_EMAIL=$(q "$JIRA_SM_EMAIL")"
[[ -n "$JIRA_SM_API_TOKEN" ]] && echo "JIRA_SM_API_TOKEN=$(q "$JIRA_SM_API_TOKEN")"
[[ -n "$JIRA_SM_PROJECT_KEY" ]] && echo "JIRA_SM_PROJECT_KEY=$(q "$JIRA_SM_PROJECT_KEY")"
[[ -n "$KUBECONFIG_PATH"  ]] && echo "KUBECONFIG_PATH=$(q "$KUBECONFIG_PATH")"
[[ -n "$AWS_ROLE_ARN"     ]] && echo "AWS_ROLE_ARN=$(q "$AWS_ROLE_ARN")"
[[ "$AWS_REGION" != "us-east-1" ]] && echo "AWS_REGION=$AWS_REGION"
[[ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]] && echo "GOOGLE_APPLICATION_CREDENTIALS=$(q "$GOOGLE_APPLICATION_CREDENTIALS")"
echo ""
echo "# ── Image variant ──────────────────────────────────────────────────────"
echo "PAGEMENOT_BUILD_TARGET=$PAGEMENOT_BUILD_TARGET"
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
say "${BOLD}Next steps:${RESET}"
say "  ${GREEN}make install${RESET}   — builds the ${BOLD}${PAGEMENOT_BUILD_TARGET}${RESET} image and starts pagemenot"
say "  ${GREEN}make test${RESET}      — fire a simulated incident to verify the setup"
