#!/usr/bin/env bash
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
heading() { echo -e "\n${BOLD}$*${NC}"; }

heading "Activity Monitor — Setup"
echo "Checking prerequisites and configuring your installation."

# ── 1. Prerequisites ─────────────────────────────────────────────────────────

command -v docker &>/dev/null || error "Docker is not installed. Install it from https://docs.docker.com/engine/install/"

# Check compose (Docker Compose V2 ships as 'docker compose')
docker compose version &>/dev/null || error "'docker compose' is not available. Update Docker to v20.10+ or install the Compose plugin."

info "Docker $(docker --version | awk '{print $3}' | tr -d ',')"

# ── 2. NVIDIA GPU detection ───────────────────────────────────────────────────

# Whether the nvidia runtime lines are currently active (not commented out)
COMPOSE_HAS_NVIDIA=$(grep -c '^    runtime: nvidia$' docker-compose.yml || true)

if docker info 2>/dev/null | grep -q 'Runtimes:.*nvidia'; then
    info "NVIDIA Container Runtime detected — GPU monitoring enabled"
    # Re-enable lines if they were previously commented out (e.g. re-running after adding a GPU)
    if [ "$COMPOSE_HAS_NVIDIA" -eq 0 ]; then
        sed -i 's/^    # runtime: nvidia$/    runtime: nvidia/' docker-compose.yml
        sed -i 's/^    # environment:$/    environment:/' docker-compose.yml
        sed -i 's/^      # - NVIDIA_VISIBLE_DEVICES=all$/      - NVIDIA_VISIBLE_DEVICES=all/' docker-compose.yml
        sed -i 's/^      # - NVIDIA_DRIVER_CAPABILITIES=utility,compute$/      - NVIDIA_DRIVER_CAPABILITIES=utility,compute/' docker-compose.yml
        info "Re-enabled NVIDIA lines in docker-compose.yml"
    fi
else
    warn "NVIDIA Container Runtime not found — GPU monitoring will be disabled"
    if [ "$COMPOSE_HAS_NVIDIA" -gt 0 ]; then
        sed -i 's/^    runtime: nvidia$/    # runtime: nvidia/' docker-compose.yml
        sed -i 's/^    environment:$/    # environment:/' docker-compose.yml
        sed -i 's/^      - NVIDIA_VISIBLE_DEVICES=all$/      # - NVIDIA_VISIBLE_DEVICES=all/' docker-compose.yml
        sed -i 's/^      - NVIDIA_DRIVER_CAPABILITIES=utility,compute$/      # - NVIDIA_DRIVER_CAPABILITIES=utility,compute/' docker-compose.yml
        info "Commented out NVIDIA lines in docker-compose.yml"
    fi
    warn "To enable GPU monitoring later: install the NVIDIA Container Toolkit and re-run ./install.sh"
fi

# ── 3. Persistent data directory ─────────────────────────────────────────────

if [ ! -d data ]; then
    mkdir -p data
    info "Created data/ directory (holds settings and metrics database)"
else
    info "data/ directory already exists"
fi

# ── 4. Environment file ───────────────────────────────────────────────────────

if [ -f .env ]; then
    info ".env already exists — skipping"
else
    cp .env.example .env
    info "Created .env from .env.example"

    # Try to auto-detect Tailscale IP
    TAILSCALE_IP=""
    if command -v tailscale &>/dev/null; then
        TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || true)
    fi
    if [ -z "$TAILSCALE_IP" ]; then
        TAILSCALE_IP=$(ip addr show 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | grep '^100\.' | head -1 || true)
    fi

    if [ -n "$TAILSCALE_IP" ]; then
        sed -i "s|^BIND_HOST=.*|BIND_HOST=${TAILSCALE_IP}|" .env
        info "Auto-detected Tailscale IP: ${TAILSCALE_IP} — set as BIND_HOST"
        warn "The dashboard will be accessible at http://${TAILSCALE_IP}:8081 from any Tailscale device"
    else
        warn "No Tailscale IP found — defaulting to BIND_HOST=127.0.0.1 (localhost only)"
        warn "Edit .env and set BIND_HOST to your Tailscale IP or 0.0.0.0 to change this"
    fi
fi

# Show current config
echo ""
echo "  Current .env settings:"
grep -v '^#' .env | grep -v '^$' | sed 's/^/    /'
echo ""

# ── 5. Build and start ────────────────────────────────────────────────────────

heading "Building and starting the container"
docker compose up -d --build

# ── 6. Health check ───────────────────────────────────────────────────────────

BIND_HOST=$(grep '^BIND_HOST=' .env 2>/dev/null | cut -d= -f2 || echo "127.0.0.1")
BIND_PORT=$(grep '^BIND_PORT=' .env 2>/dev/null | cut -d= -f2 || echo "8081")
URL="http://${BIND_HOST}:${BIND_PORT}"

echo ""
info "Waiting for the app to become healthy..."
for i in {1..15}; do
    STATUS=$(curl -sf "${URL}/health" 2>/dev/null | grep -c '"healthy"' || true)
    if [ "$STATUS" -gt 0 ]; then
        break
    fi
    sleep 1
done

if curl -sf "${URL}/health" &>/dev/null; then
    info "Health check passed"
    echo ""
    echo -e "  ${BOLD}Dashboard:${NC} ${URL}"
    echo -e "  ${BOLD}API:${NC}       ${URL}/api/all"
    echo -e "  ${BOLD}History:${NC}   ${URL}/api/history/metrics?hours=6"
    echo ""
    info "Activity Monitor is running. Use 'docker compose logs -f' to follow logs."
else
    warn "Health check did not respond — the app may still be starting (initial metric collection takes a few seconds)"
    warn "Try: curl ${URL}/health"
fi
