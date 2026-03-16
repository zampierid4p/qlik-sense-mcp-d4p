# Qlik Sense MCP Server

[![PyPI version](https://badge.fury.io/py/qlik-sense-mcp-server.svg)](https://pypi.org/project/qlik-sense-mcp-server/)
[![PyPI downloads](https://img.shields.io/pypi/dm/qlik-sense-mcp-server)](https://pypi.org/project/qlik-sense-mcp-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/pypi/pyversions/qlik-sense-mcp-server)](https://pypi.org/project/qlik-sense-mcp-server/)

Model Context Protocol (MCP) server for integration with Qlik Sense Enterprise APIs. Provides unified interface for Repository API and Engine API operations through MCP protocol.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Docker](#docker)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Overview

Qlik Sense MCP Server bridges Qlik Sense Enterprise with systems supporting Model Context Protocol. Server provides 10 comprehensive tools for complete Qlik Sense analytics workflow including application discovery, data analysis, script extraction, and metadata management.

### Key Features

- **Unified API**: Single interface for Qlik Sense Repository and Engine APIs
- **Security**: Certificate-based authentication support
- **Performance**: Optimized queries and direct API access
- **Analytics**: Advanced data analysis and hypercube creation
- **Metadata**: Comprehensive application and field information

## Features

### Available Tools

| Tool | Description | API | Status |
|------|-------------|-----|--------|
| `get_apps` | Get comprehensive list of applications with metadata | Repository | ✅ |
| `get_app_details` | Get compact app overview (metadata, fields, master items, sheets/objects) | Repository | ✅ |
| `get_app_sheets` | Get list of sheets from application with title and description | Engine | ✅ |
| `get_app_sheet_objects` | Get list of objects from specific sheet with object ID, type and description | Engine | ✅ |
| `get_app_script` | Extract load script from application | Engine | ✅ |
| `get_app_field` | Return values of a field with pagination and wildcard search | Engine | ✅ |
| `get_app_variables` | Return variables split by source with pagination and wildcard search | Engine | ✅ |
| `get_app_field_statistics` | Get comprehensive field statistics | Engine | ✅ |
| `engine_create_hypercube` | Create hypercube for data analysis | Engine | ✅ |
| `get_app_object` | Get specific object layout by ID (GetObject + GetLayout) | Engine | ✅ |

## Installation

### 1. Check Requirements

- Python 3.12+
- Qlik Sense Enterprise
- Valid certificates for authentication
- Network access to Qlik Sense server (ports 4242 Repository, 4747 Engine)
- Ensure your MCP client model can handle large JSON responses; prefer small limits in requests during testing

### 2. Verify and Install Python

This project requires **Python 3.12 or newer**. Steps vary by platform.

#### macOS

Check the installed version:

```bash
python3 --version
```

If the output shows a version older than 3.12, or the command is not found, install Python 3.12 via Homebrew:

```bash
brew install python@3.12
```

If Homebrew is not installed, run this first:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After installation check again:

```bash
python3.12 --version
```

Alternatively, download an installer directly from [python.org/downloads](https://www.python.org/downloads/).

Optional – install `uv` for faster dependency management:

```bash
brew install uv
# or, if you prefer the official installer:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Linux (Debian / Ubuntu)

Check the installed version:

```bash
python3 --version
```

If the output shows a version older than 3.12 or the command is not found:

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-pip
```

Verify installation:

```bash
python3.12 --version
```

If `python3.12` is not in your distro's package list, enable the deadsnakes PPA first:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-pip
```

#### Linux (RHEL / Fedora / Rocky)

```bash
sudo dnf install python3.12
```

Optional – install `uv` on Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Make sure the `uv` binary is in your `PATH` afterwards (the installer prints the required export).

#### Confirm before proceeding

```bash
# Should print 3.12.x or newer
python3.12 --version

# Optional – if uv was installed
uv --version
```

### 3. Choose an Installation Method

#### Option A: Run Directly with uvx (Recommended for quick use)

```bash
uvx qlik-sense-mcp-server
```

This installs and runs the latest version without modifying your main Python environment.

#### Option B: Install from PyPI

```bash
pip install qlik-sense-mcp-server
```

Use this when you want the CLI available as a normal installed command.

#### Option C: Clone the Repository for Development or Custom Deployment

```bash
git clone https://github.com/data4prime/qlik-sense-mcp-d4p.git
cd qlik-sense-mcp-d4p
make dev
```

Notes:
- `uv` is supported but not required
- If `uv` is installed, `make dev` uses it automatically
- If `uv` is not installed, the Makefile creates a local virtual environment and installs dependencies there
- If needed, force a specific Python 3.12+ interpreter: `make dev PYTHON=python3.12`

### 4. Create Runtime Configuration

After installation, prepare local configuration and certificates:

```bash
cp .env.example .env
mkdir -p certs
# Copy client.pem, client_key.pem and root.pem into ./certs
```

### 5. Update an Existing Local Clone

Use this sequence to update an existing checkout from Git:

```bash
cd /absolute/path/to/qlik-sense-mcp-d4p

# Inspect local changes before updating
git status

# Fetch branches and tags
git fetch --all --tags

# Update the current branch
git pull --rebase
```

If you want to align to a specific release tag:

```bash
git fetch --tags
git checkout v1.4.3
```

After updating the repository, refresh the local environment as needed:

```bash
make dev
make docker-build
```

If you use the remote gateway image or Docker Compose, rebuild/restart after pulling changes:

```bash
docker compose -f docker-compose.remote.yml up --build -d
```

If your local branch contains uncommitted changes, commit or stash them before `git pull --rebase`.

## Configuration

Use this section after completing Installation. The runtime configuration is the same whether you start the server from Python, Docker, or Docker Compose; only the certificate paths change depending on where the process runs.

### 1. Edit the `.env` File

Start from the provided template:

```bash
cp .env.example .env
```

Minimum example:

```bash
# Server connection
QLIK_SERVER_URL=https://your-qlik-server.company.com
QLIK_USER_DIRECTORY=COMPANY
QLIK_USER_ID=your-username

# Certificate paths (absolute paths)
QLIK_CLIENT_CERT_PATH=/path/to/certs/client.pem
QLIK_CLIENT_KEY_PATH=/path/to/certs/client_key.pem
QLIK_CA_CERT_PATH=/path/to/certs/root.pem

# API ports (standard Qlik Sense ports)
QLIK_REPOSITORY_PORT=4242
QLIK_ENGINE_PORT=4747

# Optional HTTP port for metadata requests
QLIK_HTTP_PORT=443

# SSL settings
QLIK_VERIFY_SSL=false
```

Certificate path rules:
- local Python or `uvx`: use absolute host paths such as `/Users/you/.../certs/client.pem` or `/home/you/.../certs/client.pem`
- Docker or Docker Compose: use container-internal paths such as `/certs/client.pem`, `/certs/client_key.pem`, `/certs/root.pem`

### 2. Optional Runtime Settings

```bash
# Logging level (default: INFO)
LOG_LEVEL=INFO

# HTTP request timeout (default: 10.0)
QLIK_HTTP_TIMEOUT=10.0

# Engine WebSocket timeouts and retries
QLIK_WS_TIMEOUT=8.0     # seconds
QLIK_WS_RETRIES=2       # number of endpoints to try

# Remote gateway settings (only for qlik-sense-mcp-gateway)
# MCP_AUTH_TOKEN=replace-with-long-random-token
# MCP_AUTH_PASSPHRASE=replace-with-strong-passphrase
# MCP_GATEWAY_HOST=0.0.0.0
# MCP_GATEWAY_PORT=8080
# MCP_PUBLIC_PORT=8080
# MCP_GATEWAY_PATH=/mcp
```

### 3. Variable Reference

| Group | Variables | Notes |
|---|---|---|
| Required connection | `QLIK_SERVER_URL`, `QLIK_USER_DIRECTORY`, `QLIK_USER_ID` | Always required |
| Certificates | `QLIK_CLIENT_CERT_PATH`, `QLIK_CLIENT_KEY_PATH`, `QLIK_CA_CERT_PATH` | Required in production; if CA path is omitted, SSL verification is disabled |
| Network | `QLIK_REPOSITORY_PORT`, `QLIK_PROXY_PORT`, `QLIK_ENGINE_PORT`, `QLIK_HTTP_PORT` | `QLIK_HTTP_PORT` is only used for metadata endpoint requests |
| Security | `QLIK_VERIFY_SSL` | Use `false` only for controlled testing scenarios |
| Timeouts | `QLIK_HTTP_TIMEOUT`, `QLIK_WS_TIMEOUT`, `QLIK_WS_RETRIES` | Tune only if your Qlik environment is slow or unstable |
| Logging | `LOG_LEVEL` | Supported values: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| Remote gateway | `MCP_AUTH_TOKEN`, `MCP_AUTH_PASSPHRASE`, `MCP_GATEWAY_HOST`, `MCP_GATEWAY_PORT`, `MCP_PUBLIC_PORT`, `MCP_GATEWAY_PATH` | Used only when exposing the remote HTTP gateway |

### 4. MCP Client Configuration

For local stdio integration, create an MCP client configuration like this:

Create `mcp.json` file for MCP client integration:

```json
{
  "mcpServers": {
    "qlik-sense": {
      "command": "uvx",
      "args": ["qlik-sense-mcp-server"],
      "env": {
        "QLIK_SERVER_URL": "https://your-qlik-server.company.com",
        "QLIK_USER_DIRECTORY": "COMPANY",
        "QLIK_USER_ID": "your-username",
        "QLIK_CLIENT_CERT_PATH": "/absolute/path/to/certs/client.pem",
        "QLIK_CLIENT_KEY_PATH": "/absolute/path/to/certs/client_key.pem",
        "QLIK_CA_CERT_PATH": "/absolute/path/to/certs/root.pem",
        "QLIK_REPOSITORY_PORT": "4242",
        "QLIK_PROXY_PORT": "4243",
        "QLIK_ENGINE_PORT": "4747",
        "QLIK_HTTP_PORT": "443",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_HTTP_TIMEOUT": "10.0",
        "QLIK_WS_TIMEOUT": "8.0",
        "QLIK_WS_RETRIES": "2",
        "LOG_LEVEL": "INFO"
      },
      "disabled": false,
      "autoApprove": [
        "get_apps",
        "get_app_details",
        "get_app_script",
        "get_app_field_statistics",
        "engine_create_hypercube",
        "get_app_field",
        "get_app_variables",
        "get_app_sheets",
        "get_app_sheet_objects",
        "get_app_object"
      ]
    }
  }
}
```

The repository also includes `mcp.json.example` and `claude_desktop_remote.example.json` as starting points for local or remote client integrations.

## Docker

The repository includes a multi-stage `Dockerfile`, a `docker-compose.yml`, a `docker-compose.remote.yml`, and a `.dockerignore`.

Choose the container mode that matches your client:
- stdio mode for local MCP clients launched as a command, such as Claude Desktop or Cursor
- remote HTTP gateway mode for external clients that connect over MCP Streamable HTTP

The stdio container must always be started with an open stdin using `-i`.

### Prerequisites

#### macOS

- Install Docker Desktop and ensure `docker` and `docker compose` are available in your shell
- Use absolute paths under `/Users/<your-user>/...` when configuring Claude Desktop or other MCP clients
- If you use Docker Desktop file sharing restrictions, make sure the project folder is shared with Docker

#### Linux

- Install Docker Engine plus Docker Compose plugin
- Verify access without `sudo` or prepend `sudo` to the Docker commands in this README
- If needed, add your user to the Docker group and re-login:

```bash
sudo usermod -aG docker "$USER"
```

#### Common setup

```bash
# 1. Copy the environment template and fill in your values
cp .env.example .env

# 2. Place your Qlik Sense certificates in ./certs/
#    expected filenames (configurable via env vars):
#      certs/client.pem
#      certs/client_key.pem
#      certs/root.pem
mkdir -p certs
```

Notes:
- The shell examples in this README use POSIX syntax and work as-is in macOS `zsh` and standard Linux shells such as `bash` and `zsh`
- The bind-mount examples use `$(pwd)`, which works on both macOS and Linux
- If mounted certificate files are not readable inside the container, verify host-side file permissions before troubleshooting TLS

### 1. Prepare Runtime Files

```bash
cp .env.example .env
mkdir -p certs
```

Then copy `client.pem`, `client_key.pem`, and `root.pem` into `./certs` and set Docker-friendly certificate paths in `.env`:

```bash
QLIK_CLIENT_CERT_PATH=/certs/client.pem
QLIK_CLIENT_KEY_PATH=/certs/client_key.pem
QLIK_CA_CERT_PATH=/certs/root.pem
```

### 2. Build the Image

```bash
docker build -t qlik-sense-mcp-server .
```

### 3. Run in Stdio Mode

Standalone container:

```bash
docker run -i --rm \
  --env-file .env \
  -v "$(pwd)/certs:/certs:ro" \
  qlik-sense-mcp-server
```

With Docker Compose:

```bash
docker compose up --build
```

Use stdio mode when your MCP client launches the server process directly.

### 4. Configure a Local MCP Client to Use Docker

To use the Docker container as the MCP server in a client such as Claude Desktop or Cursor, set the `command` to `docker run` with `-i`:

```json
{
  "mcpServers": {
    "qlik-sense": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--env-file", "/absolute/path/to/.env",
        "-v", "/absolute/path/to/certs:/certs:ro",
        "qlik-sense-mcp-server"
      ]
    }
  }
}
```

Path notes:
- macOS example absolute paths usually look like `/Users/<user>/projects/qlik-sense-mcp-d4p/.env`
- Linux example absolute paths usually look like `/home/<user>/projects/qlik-sense-mcp-d4p/.env`

### 5. Run the Remote MCP Gateway

Set at least one remote credential in `.env` or through the shell:

```bash
MCP_AUTH_TOKEN=replace-with-long-random-token
# or
MCP_AUTH_PASSPHRASE=replace-with-strong-passphrase
```

Start the gateway:

```bash
docker compose -f docker-compose.remote.yml up --build -d
```

Validate it:

```bash
curl http://localhost:8080/healthz
```

Authentication headers accepted by the gateway:

```http
Authorization: Bearer <MCP_AUTH_TOKEN>
```

Alternative header:

```http
X-MCP-Token: <MCP_AUTH_TOKEN>
```

Use the slash-suffixed endpoint URL `/mcp/` when testing manually to avoid redirect responses.

### 6. Claude Desktop Remote Configuration

Use the remote gateway URL and send the bearer token in headers.

Typical config file locations:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json` if your Claude Desktop build uses the standard XDG config path

```json
{
  "mcpServers": {
    "qlik-sense-remote": {
      "transport": "streamable-http",
      "url": "https://your-mcp-host.example.com/mcp/",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

Quick local test after `docker compose -f docker-compose.remote.yml up -d`:

```json
{
  "mcpServers": {
    "qlik-sense-remote": {
      "transport": "streamable-http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

Notes:
- endpoint path is configurable with `MCP_GATEWAY_PATH` and defaults to `/mcp`
- the gateway supports MCP Streamable HTTP with `GET`, `POST`, and `DELETE`
- keep token or passphrase in external secret management where possible
- place the gateway behind TLS reverse proxy before exposing it on the internet

### 7. Deploy from a Private Docker Hub Repository

Use this sequence when your image is published to a private Docker Hub repository.

On Linux, prepend `sudo` to Docker commands if your user is not configured for rootless access or not in the `docker` group.

1. Authenticate to Docker Hub:

```bash
docker login
```

2. Define image coordinates (example):

```bash
export DOCKERHUB_USER=your-dockerhub-user
export IMAGE_NAME=qlik-sense-mcp-server
export IMAGE_TAG=1.4.3
export IMAGE_REF="$DOCKERHUB_USER/$IMAGE_NAME:$IMAGE_TAG"
```

3. Pull the image from your private repository:

```bash
docker pull "$IMAGE_REF"
```

4. Prepare runtime config (if not already done):

```bash
cp .env.example .env
mkdir -p certs
# copy client.pem, client_key.pem, root.pem into ./certs
```

5. Start in stdio mode (for local MCP clients such as Claude Desktop/Cursor launched via command):

```bash
docker run -i --rm \
  --env-file .env \
  -v "$(pwd)/certs:/certs:ro" \
  "$IMAGE_REF"
```

6. Or start in remote HTTP gateway mode (for remote MCP clients):

```bash
docker run --rm -d \
  --name qlik-sense-mcp-remote \
  --env-file .env \
  -e MCP_AUTH_TOKEN=replace-with-strong-token \
  -e MCP_GATEWAY_HOST=0.0.0.0 \
  -e MCP_GATEWAY_PORT=8080 \
  -e MCP_GATEWAY_PATH=/mcp \
  -v "$(pwd)/certs:/certs:ro" \
  -p 8080:8080 \
  --entrypoint qlik-sense-mcp-gateway \
  "$IMAGE_REF"
```

7. Validate remote gateway:

```bash
curl http://localhost:8080/healthz
```

8. If you use Docker Compose and want to force private-registry image without local build:

```bash
DOCKER_IMAGE_REF="$IMAGE_REF" docker compose -f docker-compose.remote.yml up -d --no-build
```

Then set in compose file `image: ${DOCKER_IMAGE_REF}` (replace static image value) or export the variable in your shell before startup.

### Docker environment variables

All variables from [Configuration](#configuration) are supported.
The defaults baked into the image are:

| Variable | Default in image |
|---|---|
| `QLIK_REPOSITORY_PORT` | `4242` |
| `QLIK_PROXY_PORT` | `4243` |
| `QLIK_ENGINE_PORT` | `4747` |
| `QLIK_VERIFY_SSL` | `true` |
| `LOG_LEVEL` | `INFO` |

All other variables (`QLIK_SERVER_URL`, `QLIK_USER_DIRECTORY`, `QLIK_USER_ID`, cert paths, etc.) **must** be provided at runtime — they are never baked into the image.

### Certificate mount path

The image exposes `/certs` as the default mount target. Override the cert paths freely:

```bash
docker run -i --rm \
  --env-file .env \
  -e QLIK_CLIENT_CERT_PATH=/secrets/client.pem \
  -e QLIK_CLIENT_KEY_PATH=/secrets/client_key.pem \
  -e QLIK_CA_CERT_PATH=/secrets/root.pem \
  -v /my/custom/cert/dir:/secrets:ro \
  qlik-sense-mcp-server
```

## Usage

### Start Server

Choose one launch mode based on the client you are using.

#### Local stdio mode

```bash
# Using uvx (recommended)
uvx qlik-sense-mcp-server

# Using installed package
qlik-sense-mcp-server

# From source (development)
python -m qlik_sense_mcp_server.server

# Using Docker
docker run -i --rm --env-file .env -v "$(pwd)/certs:/certs:ro" qlik-sense-mcp-server
```

#### Remote HTTP gateway mode

```bash
# From installed package
qlik-sense-mcp-gateway

# Using Docker Compose
docker compose -f docker-compose.remote.yml up --build -d
```

### Example Operations

#### Get Applications List
```python
# Via MCP client - get first 50 apps (default)
result = mcp_client.call_tool("get_apps")
print(f"Showing {result['pagination']['returned']} of {result['pagination']['total_found']} apps")

# Search for specific apps
result = mcp_client.call_tool("get_apps", {
    "name_filter": "Sales",
    "limit": 10
})

# Get more apps (pagination)
result = mcp_client.call_tool("get_apps", {
    "offset": 50,
    "limit": 50
})
```

#### Analyze Application
```python
# Get comprehensive app analysis
result = mcp_client.call_tool("get_app_details", {
    "app_id": "your-app-id"
})
print(f"App has {len(result['data_model']['tables'])} tables")
```

#### Create Data Analysis Hypercube
```python
# Create hypercube for sales analysis
result = mcp_client.call_tool("engine_create_hypercube", {
    "app_id": "your-app-id",
    "dimensions": ["Region", "Product"],
    "measures": ["Sum(Sales)", "Count(Orders)"],
    "max_rows": 1000
})
```

#### Get Field Statistics
```python
# Get detailed field statistics
result = mcp_client.call_tool("get_app_field_statistics", {
    "app_id": "your-app-id",
    "field_name": "Sales"
})
print(f"Average: {result['avg_value']['numeric']}")
```

## API Reference

### get_apps
Retrieves comprehensive list of Qlik Sense applications with metadata, pagination and filtering support.

**Parameters:**
- `limit` (optional): Maximum number of apps to return (default: 50, max: 1000)
- `offset` (optional): Number of apps to skip for pagination (default: 0)
- `name_filter` (optional): Filter apps by name (case-insensitive partial match)
- `app_id_filter` (optional): Filter by specific app ID/GUID
- `include_unpublished` (optional): Include unpublished apps (default: true)

**Returns:** Object containing paginated apps, streams, and pagination metadata

**Example (default - first 50 apps):**
```json
{
  "apps": [...],
  "streams": [...],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "returned": 50,
    "total_found": 1598,
    "has_more": true,
    "next_offset": 50
  },
  "filters": {
    "name_filter": null,
    "app_id_filter": null,
    "include_unpublished": true
  },
  "summary": {
    "total_apps": 1598,
    "published_apps": 857,
    "private_apps": 741,
    "total_streams": 40,
    "showing": "1-50 of 1598"
  }
}
```

**Example (with name filter):**
```python
# Search for apps containing "dashboard"
result = mcp_client.call_tool("get_apps", {
    "name_filter": "dashboard",
    "limit": 10
})

# Get specific app by ID
result = mcp_client.call_tool("get_apps", {
    "app_id_filter": "e2958865-2aed-4f8a-b3c7-20e6f21d275c"
})

# Get next page of results
result = mcp_client.call_tool("get_apps", {
    "limit": 50,
    "offset": 50
})
```

### get_app_details
Gets comprehensive application analysis including data model, object counts, and metadata. Provides detailed field information, table structures, and application properties.

**Parameters:**
- `app_id` (required): Application identifier

**Returns:** Detailed application object with data model structure

**Example:**
```json
{
  "app_metadata": {...},
  "data_model": {
    "tables": [...],
    "total_tables": 2,
    "total_fields": 45
  },
  "object_counts": {...}
}
```

### get_app_sheets
Get list of sheets from application with title and description.

**Parameters:**
- `app_id` (required): Application GUID

**Returns:** Object containing application sheets with their IDs, titles and descriptions

**Example:**
```json
{
  "app_id": "e2958865-2aed-4f8a-b3c7-20e6f21d275c",
  "total_sheets": 2,
  "sheets": [
    {
      "sheet_id": "abc123-def456-ghi789",
      "title": "Main Dashboard",
      "description": "Primary analysis dashboard"
    },
    {
      "sheet_id": "def456-ghi789-jkl012",
      "title": "Detailed Analysis",
      "description": "Detailed data analysis"
    }
  ]
}
```

### get_app_sheet_objects
Retrieves list of objects from a specific sheet in Qlik Sense application with their metadata.

**Parameters:**
- `app_id` (required): Application identifier
- `sheet_id` (required): Sheet identifier

**Returns:** Object containing sheet objects with their IDs, types and descriptions

**Example:**
```json
{
  "app_id": "e2958865-2aed-4f8a-b3c7-20e6f21d275c",
  "sheet_id": "abc123-def456-ghi789",
  "total_objects": 3,
  "objects": [
    {
      "object_id": "chart-1",
      "object_type": "barchart",
      "object_description": "Sales by Region"
    },
    {
      "object_id": "table-1",
      "object_type": "table",
      "object_description": "Customer Details"
    },
    {
      "object_id": "kpi-1",
      "object_type": "kpi",
      "object_description": "Total Revenue"
    }
  ]
}
```

### get_app_object
Retrieves layout of a specific object by its ID using sequential GetObject and GetLayout requests.

**Parameters:**
- `app_id` (required): Application identifier
- `object_id` (required): Object identifier

**Returns:** Object layout structure as returned by GetLayout

**Example:**
```json
{
  "qLayout": {
    "...": "..."
  }
}
```

### get_app_script
Retrieves load script from application.

**Parameters:**
- `app_id` (required): Application identifier

**Returns:** Object containing script text and metadata

**Example:**
```json
{
  "qScript": "SET DateFormat='DD.MM.YYYY';\n...",
  "app_id": "app-id",
  "script_length": 2830
}
```

### get_app_field
Returns values of a single field with pagination and optional wildcard search.

**Parameters:**
- `app_id` (required): Application GUID
- `field_name` (required): Field name
- `limit` (optional): Number of values to return (default: 10, max: 100)
- `offset` (optional): Offset for pagination (default: 0)
- `search_string` (optional): Wildcard text mask with `*` and `%` support
- `search_number` (optional): Wildcard numeric mask with `*` and `%` support
- `case_sensitive` (optional): Case sensitivity for `search_string` (default: false)

**Returns:** Object containing field values

**Example:**
```json
{
  "field_values": [
    "Russia",
    "USA",
    "China"
  ]
}
```

### get_app_variables
Returns variables split by source (script/ui) with pagination and wildcard search.

**Parameters:**
- `app_id` (required): Application GUID
- `limit` (optional): Max variables to return (default: 10, max: 100)
- `offset` (optional): Offset for pagination (default: 0)
- `created_in_script` (optional): Return only variables created in script (true/false). If omitted, return both
- `search_string` (optional): Wildcard search by variable name or text value (* and % supported), case-insensitive by default
- `search_number` (optional): Wildcard search among numeric variable values (* and % supported)
- `case_sensitive` (optional): Case sensitive matching for search_string (default: false)

**Returns:** Object containing variables from script and UI

**Example:**
```json
{
  "variables_from_script": {
    "vSalesTarget": "1000000",
    "vCurrentYear": "2024"
  },
  "variables_from_ui": {
    "vSelectedRegion": "Europe",
    "vDateRange": "Q1-Q4"
  }
}
```

### get_app_field_statistics
Retrieves comprehensive field statistics.

**Parameters:**
- `app_id` (required): Application identifier
- `field_name` (required): Field name

**Returns:** Statistical analysis including min, max, average, median, mode, standard deviation

**Example:**
```json
{
  "field_name": "age",
  "min_value": {"numeric": 0},
  "max_value": {"numeric": 2023},
  "avg_value": {"numeric": 40.98},
  "median_value": {"numeric": 38},
  "std_deviation": {"numeric": 24.88}
}
```

### engine_create_hypercube
Creates hypercube for data analysis.

**Parameters:**
- `app_id` (required): Application identifier
- `dimensions` (required): Array of dimension fields
- `measures` (required): Array of measure expressions
- `max_rows` (optional): Maximum rows to return (default: 1000)

**Returns:** Hypercube data with dimensions, measures, and total statistics

**Example:**
```json
{
  "hypercube_data": {
    "qDimensionInfo": [...],
    "qMeasureInfo": [...],
    "qDataPages": [...]
  },
  "total_rows": 30,
  "total_columns": 4
}
```

## Architecture

### Project Structure
```
qlik-sense-mcp-d4p/
├── qlik_sense_mcp_server/
│   ├── __init__.py
│   ├── server.py          # Main MCP server
│   ├── remote_gateway.py  # Remote Streamable HTTP gateway with token auth
│   ├── config.py          # Configuration management
│   ├── repository_api.py  # Repository API client (HTTP)
│   ├── engine_api.py      # Engine API client (WebSocket)
│   └── utils.py           # Utility functions
├── certs/                 # Certificates (git ignored)
│   ├── client.pem
│   ├── client_key.pem
│   └── root.pem
├── .env.example          # Configuration template
├── .dockerignore         # Docker build exclusions
├── docker-compose.yml    # Docker Compose configuration
├── docker-compose.remote.yml # Remote MCP gateway deployment
├── Dockerfile            # Multi-stage container build
├── mcp.json.example      # MCP configuration template
├── pyproject.toml        # Project dependencies
└── README.md
```

### System Components

#### QlikSenseMCPServer
Main server class handling MCP protocol operations, tool registration, and request routing.

#### QlikRepositoryAPI
HTTP client for Repository API operations including application metadata and administrative functions.

#### QlikEngineAPI
WebSocket client for Engine API operations including data extraction, analytics, and hypercube creation.

#### QlikSenseConfig
Configuration management class handling environment variables, certificate paths, and connection settings.

## Development

### Development Environment Setup

```bash
# Setup development environment
make dev

# Show all available commands
make help

# Build package
make build
```

If `uv` is not available in the current shell, these Make targets automatically create and use a local virtual environment, provided the selected Python interpreter is version 3.12 or newer.

### Version Management

```bash
# Bump patch version and create PR
make version-patch

# Bump minor version and create PR
make version-minor

# Bump major version and create PR
make version-major
```

### Adding New Tools

1. **Add tool definition in server.py**
```python
# In tools_list
Tool(name="new_tool", description="Tool description", inputSchema={...})
```

2. **Add handler in server.py**
```python
# In handle_call_tool()
elif name == "new_tool":
    result = await asyncio.to_thread(self.api_client.new_method, arguments)
    return [TextContent(type="text", text=json.dumps(result, indent=2))]
```

3. **Implement method in API client**
```python
# In repository_api.py or engine_api.py
def new_method(self, param: str) -> Dict[str, Any]:
    """Method implementation."""
    return result
```

## Troubleshooting

### Common Issues

#### Certificate Errors
```
SSL: CERTIFICATE_VERIFY_FAILED
```
**Solution:**
- Verify certificate paths in `.env`
- Check certificate expiration
- Set `QLIK_VERIFY_SSL=false` for testing

#### Connection Errors
```
ConnectionError: Failed to connect to Engine API
```
**Solution:**
- Verify port 4747 accessibility
- Check server URL correctness
- Verify firewall settings

#### Authentication Errors
```
401 Unauthorized
```
**Solution:**
- Verify `QLIK_USER_DIRECTORY` and `QLIK_USER_ID`
- Check user exists in Qlik Sense
- Verify user permissions

#### Remote Gateway Authentication Errors
```
401 Unauthorized
```
**Solution:**
- Verify `MCP_AUTH_TOKEN` or `MCP_AUTH_PASSPHRASE` is set before starting `qlik-sense-mcp-gateway`
- Confirm the client sends `Authorization: Bearer <token>` or `X-MCP-Token: <token>`
- When testing manually, call the slash-suffixed endpoint such as `/mcp/`

#### Local Setup Errors
```
Python 3.12+ is required. Set PYTHON=python3.12 or use UV=<command>.
```
**Solution:**
- Install Python 3.12 or newer
- Run `make dev PYTHON=python3.12` if multiple Python versions are installed
- On Linux, install the virtual environment support package if needed before rerunning `make dev`

### Diagnostics

#### Test Configuration
```bash
python -c "
from qlik_sense_mcp_server.config import QlikSenseConfig
config = QlikSenseConfig.from_env()
print('Config valid:', config and hasattr(config, 'server_url'))
print('Server URL:', getattr(config, 'server_url', 'Not set'))
"
```

#### Test Repository API
```bash
python -c "
from qlik_sense_mcp_server.server import QlikSenseMCPServer
server = QlikSenseMCPServer()
print('Server initialized:', server.config_valid)
"
```

## Performance

### Optimization Recommendations

1. Start with small `limit`, `offset`, and `max_rows` values while validating a new workflow.
2. Prefer Repository API-backed tools for metadata discovery before opening Engine API sessions.
3. Query only the fields, variables, sheets, or objects required by the current analysis step.
4. Use pagination for large app inventories instead of requesting the entire catalog in a single call.
5. Reserve hypercube extraction for focused analytical queries, not broad exploratory dumps.

### Benchmarks

| Operation | Average Time | Recommendations |
|-----------|--------------|-----------------|
| get_apps | 0.5s | Use filters |
| get_app_details | 0.5s-2s | Analyze specific apps |
| get_app_sheets | 0.3-1s | Fast metadata retrieval |
| get_app_sheet_objects | 0.5-2s | Sheet analysis |
| get_app_script | 1-5s | Script extraction |
| get_app_field | 0.5-2s | Field values with pagination |
| get_app_variables | 0.3-1s | Variable listing |
| get_app_field_statistics | 0.5-2s | Use for numeric fields |
| engine_create_hypercube | 1-10s | Limit dimensions and measures |

## Security

### Recommendations

1. Keep certificates, tokens, passphrases, and `.env` files out of Git and externalize them through secret management where possible.
2. Use a dedicated Qlik service account with the minimum permissions required for the enabled MCP tools.
3. Prefer the remote gateway only behind TLS termination and rotate `MCP_AUTH_TOKEN` or `MCP_AUTH_PASSPHRASE` regularly.
4. Keep `QLIK_VERIFY_SSL=true` in production and disable verification only for temporary diagnostics in controlled environments.
5. Monitor gateway access logs and Qlik API usage so failed authentication or abnormal query patterns are visible quickly.

### Access Control

Create user in QMC with minimal required permissions:
- Read applications
- Access Engine API
- View data (if needed for analysis)

## License

MIT License

Copyright (c) 2025 Stanislav Chernov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

**Project Status**: Production Ready | 10/10 Tools Working | v1.4.3

**Installation**: `uvx qlik-sense-mcp-server`
