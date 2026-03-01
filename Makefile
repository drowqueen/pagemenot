.DEFAULT_GOAL := help

# ── Colours ───────────────────────────────────────────────────────────────────
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RESET  := \033[0m

# ── Helpers ───────────────────────────────────────────────────────────────────
.PHONY: help install start stop restart logs status test hooks

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install    first-time setup: validate config, pull image, start"
	@echo "  start      docker compose up -d"
	@echo "  stop       docker compose down"
	@echo "  restart    docker compose restart"
	@echo "  logs       follow container logs"
	@echo "  status     show running containers + enabled integrations"
	@echo "  test       fire a simulated incident (usage: make test SCENARIO=payment-500s)"
	@echo "  hooks      install git pre-commit/pre-push hooks"

# ── install ───────────────────────────────────────────────────────────────────
install: _check_docker _check_env _check_required
	@echo "$(GREEN)Config OK — starting pagemenot...$(RESET)"
	docker compose pull
	docker compose up -d
	@echo ""
	@echo "$(GREEN)✓ pagemenot is running$(RESET)"
	@echo "  Logs:  make logs"
	@echo "  Test:  make test"

# ── start / stop / restart ────────────────────────────────────────────────────
start:
	docker compose up -d

stop:
	docker compose down

restart:
	docker compose restart

# ── logs ──────────────────────────────────────────────────────────────────────
logs:
	docker compose logs -f

# ── status ────────────────────────────────────────────────────────────────────
status:
	@docker compose ps
	@echo ""
	@echo "Enabled integrations:"
	@grep -E "^[A-Z_]+=.+" .env | grep -v "TOKEN\|KEY\|SECRET\|PASSWORD" | grep -E "URL|ORG|SITE|ACCOUNT" || echo "  (none beyond Slack)"

# ── test ──────────────────────────────────────────────────────────────────────
SCENARIO ?= payment-500s
test:
	python scripts/simulate_incident.py $(SCENARIO)

# ── hooks ─────────────────────────────────────────────────────────────────────
hooks:
	bash scripts/install-hooks.sh

# ── internal checks ───────────────────────────────────────────────────────────
_check_docker:
	@if ! docker info > /dev/null 2>&1; then \
		echo "$(RED)Docker is not running. Start Docker Desktop (or the Docker daemon) and try again.$(RESET)"; \
		exit 1; \
	fi

_check_env:
	@if [ ! -f .env ]; then \
		echo "$(YELLOW)No .env found — copying from .env.example$(RESET)"; \
		cp .env.example .env; \
		echo "$(RED)Edit .env with your credentials, then run make install again.$(RESET)"; \
		exit 1; \
	fi

_check_required:
	@missing=""; \
	for var in SLACK_BOT_TOKEN SLACK_APP_TOKEN; do \
		val=$$(grep -E "^$$var=" .env | cut -d= -f2-); \
		if [ -z "$$val" ] || echo "$$val" | grep -qE "^\.\.\.|^xoxb-\.\.\.|^xapp-\.\.\."; then \
			missing="$$missing $$var"; \
		fi; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "$(RED)Missing or unset required vars in .env:$$missing$(RESET)"; \
		exit 1; \
	fi
