#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Pagemenot — Universal deploy script
# Works on: AWS, GCP, Hetzner, DigitalOcean, Vultr, Linode,
#           bare metal, Raspberry Pi, any Ubuntu/Debian box
# ═══════════════════════════════════════════════════════════

set -euo pipefail

echo "🦞 Installing Pagemenot..."

# ── Install Docker ────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# ── Install Docker Compose plugin ─────────────────────────
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose plugin..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
fi

# ── Clone and setup ───────────────────────────────────────
cd /opt
if [ ! -d "pagemenot" ]; then
    git clone https://github.com/yourname/pagemenot.git
fi
cd pagemenot

# ── Create .env if not exists ─────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  ⚠️  Edit /opt/pagemenot/.env with your API keys"
    echo "  Then run: cd /opt/pagemenot && docker compose up -d"
    echo "═══════════════════════════════════════════════════"
else
    # .env exists, start it up
    docker compose pull
    docker compose up -d
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  🦞 Pagemenot is running!"
    echo "  Health: curl http://localhost:8080/health"
    echo "═══════════════════════════════════════════════════"
fi
