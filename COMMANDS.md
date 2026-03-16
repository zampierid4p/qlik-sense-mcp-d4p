# Quick Commands Reference

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

# Run stdio container
docker run -i --rm --env-file .env -v "$(pwd)/certs:/certs:ro" qlik-sense-mcp-server

# Start remote HTTP gateway
docker compose -f docker-compose.remote.yml up --build -d

# Check gateway health
curl http://localhost:8080/healthz
```

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
- `DOCKER_IMAGE_TAG=1.4.5`
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
git checkout v1.4.5
```

After updating code, refresh local dependencies and images as needed:

```bash
make dev
make docker-build
docker compose -f docker-compose.remote.yml up --build -d
```

## Dangerous Maintenance

```bash
# Reset repository history completely (destructive)
make git-clean
```
