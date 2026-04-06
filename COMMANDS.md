# Quick Commands Reference

## Recommended Sequence (Install + Run)

```bash
# 1) Clone and prepare environment
git clone https://github.com/data4prime/qlik-sense-mcp-d4p.git
cd qlik-sense-mcp-d4p
make dev

# 2) Create runtime config and certificates
cp .env.example .env
mkdir -p certs
# copy client.pem, client_key.pem, root.pem into ./certs

# Configure remote auth mode in .env
# MCP_AUTH_MODE=token|jwt|both
# token mode: MCP_AUTH_TOKEN (or MCP_AUTH_PASSPHRASE)
# jwt mode: MCP_JWT_SECRET (+ optional MCP_JWT_AUDIENCE, MCP_JWT_ISSUER)

# 3) Run tests (recommended)
make test

# 4) Start remote gateway (n8n / HTTP MCP clients)
make remote-up

# 5) Validate liveness/readiness
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/readyz
```

Important for HTTP clients (including n8n):
- Use endpoint with trailing slash: `/mcp/`
- Send `Accept: application/json, text/event-stream`
- Reuse `mcp-session-id` from initialize response headers on subsequent calls

## Local Installation

```bash
# Run latest published version without installing into the main environment
uvx qlik-sense-mcp-server

# Install package globally or inside an existing environment
pip install qlik-sense-mcp-server

# Start stdio server after installation
qlik-sense-mcp-server

# Start remote HTTP gateway after installation
qlik-sense-mcp-gateway
```

## Python Environment

Verify the installed version:

```bash
python3 --version
```

macOS – install Python 3.12 if missing or too old:

```bash
brew install python@3.12
# optional: faster toolchain
brew install uv
```

Linux (Debian / Ubuntu) – install Python 3.12 if missing or too old:

```bash
sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-pip
```

Linux (RHEL / Fedora):

```bash
sudo dnf install python3.12
```

Optional – install `uv` on any platform:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Confirm before proceeding:

```bash
python3.12 --version  # must be 3.12 or newer
```

## Repository Setup

```bash
# Clone the repository
git clone https://github.com/data4prime/qlik-sense-mcp-d4p.git
cd qlik-sense-mcp-d4p

# Create development environment
make dev

# Show available targets
make help
```

Notes:
- Python 3.12+ is required
- If `uv` is unavailable, `make dev` creates a local virtual environment automatically
- To force a specific interpreter: `make dev PYTHON=python3.12`

## Runtime Configuration

```bash
# Copy template and create local certificate folder
cp .env.example .env
mkdir -p certs
```

For local Python execution, use absolute host paths in `.env` for certificate variables.
For Docker or Docker Compose, use container paths such as `/certs/client.pem`.

## Docker

```bash
# Build image with version from pyproject.toml
make docker-build

# Or build manually with a fixed local tag
docker build -t qlik-sense-mcp-server .

# Optional: include Chromium for headless fallback in get_visualization_image
docker build --build-arg INSTALL_PLAYWRIGHT=true -t qlik-sense-mcp-server:playwright .

# Run stdio container
docker run -i --rm --env-file .env -v "$(pwd)/certs:/certs:ro" qlik-sense-mcp-server

# Start remote HTTP gateway from docker-compose.remote.yml
make remote-up

# Check gateway liveness
curl http://localhost:8080/healthz

# Check gateway readiness
curl http://localhost:8080/readyz

# Verify remote auth and Streamable HTTP handshake contract
curl -i http://localhost:8080/mcp/
curl -i -H "Authorization: Bearer YOUR_MCP_AUTH_TOKEN" -H "Accept: text/event-stream" http://localhost:8080/mcp/

# Minimal initialize probe (captures mcp-session-id)
AUTH_HEADER="Bearer replace-with-long-random-token"
curl -i -X POST http://localhost:8080/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: $AUTH_HEADER" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'

# If using JWT mode, set AUTH_HEADER to: Bearer <signed-jwt>

# Run the full local smoke test against the remote endpoint
make remote-smoke

# Follow remote gateway logs during development
make remote-logs

# Stop the remote gateway
make remote-down
```

Headless fallback for `get_visualization_image`:
- Default flow is API-first (no browser required)
- Enable fallback with tool argument `headless_fallback=true`
- Browser runtime knobs in `.env`: `HEADLESS_SCREENSHOT_TIMEOUT`, `HEADLESS_VIEWPORT_WIDTH`, `HEADLESS_VIEWPORT_HEIGHT`, `HEADLESS_BROWSER_EXECUTABLE`

Notes:
- `docker-compose.yml` is for stdio transport and does not publish a host port
- `docker-compose.remote.yml` is for Streamable HTTP transport and publishes `MCP_PUBLIC_PORT`
- If `8080` is already busy locally, set `MCP_PUBLIC_PORT` in `.env` and restart with `make remote-up`

Remote auth modes (`MCP_AUTH_MODE`):
- `token` (default): static token via `MCP_AUTH_TOKEN` or `MCP_AUTH_PASSPHRASE`
- `jwt`: JWT HS256 via `MCP_JWT_SECRET` (optional checks: `MCP_JWT_AUDIENCE`, `MCP_JWT_ISSUER`)
- `both`: accepts both static token and JWT

## Testing and Build

```bash
# Run test suite
make test

# Build distribution artifacts
make build
```

## Version Management

```bash
# Bump version and open release PR workflow
make version-patch
make version-minor
make version-major
```

## Docker Hub Publishing

```bash
# Push version tag only
DOCKERHUB=datasynapsi make docker-push

# Push version tag and latest
DOCKERHUB=datasynapsi make docker-push-latest
```

Optional overrides:
- `DOCKER_IMAGE_NAME=qlik-sense-mcp-server`
- `DOCKER_IMAGE_TAG=1.5.0`
- `DOCKER='sudo docker'` on Linux if needed

## Git Update Workflow

```bash
# Inspect local changes
git status

# Refresh branches and tags
git fetch --all --tags

# Update current branch
git pull --rebase

# Move to a specific release tag
git checkout v1.5.0
```

After updating code, refresh local dependencies and images as needed:

```bash
make dev
make docker-build
make remote-up
```

## Dangerous Maintenance

```bash
# Reset repository history completely (destructive)
make git-clean
```
