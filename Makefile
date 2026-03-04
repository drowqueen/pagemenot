.DEFAULT_GOAL := help

# ── Colours ───────────────────────────────────────────────────────────────────
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RESET  := \033[0m

# ── Helpers ───────────────────────────────────────────────────────────────────
.PHONY: help install start stop restart logs status test hooks demo-k8s

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install      first-time setup: validate config, pull image, start"
	@echo "  start        docker compose up -d"
	@echo "  stop         docker compose down"
	@echo "  restart      docker compose restart"
	@echo "  logs         follow container logs"
	@echo "  status       show running containers + enabled integrations"
	@echo "  test         fire a simulated incident (usage: make test SCENARIO=payment-500s)"
	@echo "  hooks        install git pre-commit/pre-push hooks"
	@echo "  demo-k8s     provision demo namespace in minikube with all resources needed to test runbooks"

# ── install ───────────────────────────────────────────────────────────────────
install: _check_docker _check_env _check_required
	@echo "$(GREEN)Config OK — building and starting pagemenot...$(RESET)"
	docker compose build
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

# ── demo-k8s ──────────────────────────────────────────────────────────────────
DEMO_NS     ?= demo
DEMO_IMAGE  ?= nginx:alpine
demo-k8s:
	@echo "$(GREEN)Provisioning demo namespace '$(DEMO_NS)' in minikube...$(RESET)"
	kubectl get ns $(DEMO_NS) > /dev/null 2>&1 || kubectl create namespace $(DEMO_NS)
	@echo "→ Deployments"
	@for svc in payment-service checkout-service api-gateway nginx-cache frontend-api user-service; do \
		kubectl get deployment $$svc -n $(DEMO_NS) > /dev/null 2>&1 \
		&& echo "  $$svc: exists" \
		|| (kubectl create deployment $$svc --image=$(DEMO_IMAGE) -n $(DEMO_NS) > /dev/null && echo "  $$svc: created"); \
	done
	@echo "→ Rollout history (patch to generate revision 2)"
	@for svc in payment-service checkout-service api-gateway nginx-cache frontend-api user-service; do \
		kubectl patch deployment $$svc -n $(DEMO_NS) \
		  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"pagemenot/demo\":\"v2\"}}}}}" \
		  > /dev/null 2>&1 && true; \
	done
	@echo "→ HPAs"
	@for svc in payment-service checkout-service api-gateway nginx-cache frontend-api user-service; do \
		kubectl get hpa $$svc -n $(DEMO_NS) > /dev/null 2>&1 \
		&& echo "  $$svc hpa: exists" \
		|| (kubectl autoscale deployment $$svc --min=1 --max=5 --cpu-percent=80 -n $(DEMO_NS) > /dev/null && echo "  $$svc hpa: created"); \
	done
	@echo "→ TLS secret (api-gateway-tls)"
	@kubectl get secret api-gateway-tls -n $(DEMO_NS) > /dev/null 2>&1 \
	  && echo "  api-gateway-tls: exists" \
	  || (openssl req -x509 -newkey rsa:2048 -keyout /tmp/demo-gw.key -out /tmp/demo-gw.crt \
	       -days 365 -nodes -subj "/CN=api-gateway" > /dev/null 2>&1 \
	       && kubectl create secret tls api-gateway-tls --cert=/tmp/demo-gw.crt --key=/tmp/demo-gw.key \
	          -n $(DEMO_NS) > /dev/null && echo "  api-gateway-tls: created")
	@echo "→ Ingress (api-gateway)"
	@kubectl get ingress api-gateway -n $(DEMO_NS) > /dev/null 2>&1 \
	  && echo "  api-gateway ingress: exists" \
	  || (kubectl create ingress api-gateway --rule="api.example.com/=api-gateway:80" \
	       -n $(DEMO_NS) > /dev/null && echo "  api-gateway ingress: created")
	@echo "→ metrics-server addon"
	@minikube addons enable metrics-server > /dev/null 2>&1 && echo "  metrics-server: enabled" || true
	@echo ""
	@echo "$(GREEN)✓ demo namespace ready$(RESET)"
	@kubectl get deployments,hpa,ingress,secret -n $(DEMO_NS) 2>/dev/null

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
