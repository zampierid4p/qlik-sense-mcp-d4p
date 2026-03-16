# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir hatchling build

# Copy only what is needed to build the wheel
COPY pyproject.toml README.md ./
COPY qlik_sense_mcp_server/ ./qlik_sense_mcp_server/

# Build the wheel
RUN python -m build --wheel --outdir /dist

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Metadata
LABEL org.opencontainers.image.title="Qlik Sense MCP Server" \
      org.opencontainers.image.description="MCP Server for Qlik Sense Enterprise APIs" \
      org.opencontainers.image.source="https://github.com/data4prime/qlik-sense-mcp-d4p"

# Create a non-root user
RUN addgroup --system mcp && adduser --system --ingroup mcp --no-create-home mcp

WORKDIR /app

# Install the wheel built in the previous stage
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Directory where certificates are expected to be mounted at runtime.
# The paths below correspond to the QLIK_*_CERT_PATH env-var defaults used
# in docker-compose.yml; override them freely with environment variables.
RUN mkdir -p /certs && chown mcp:mcp /certs

USER mcp

# ── Environment variables (all optional; override at runtime) ─────────────────
# Non-sensitive defaults baked into the image.
# Sensitive values (server URL, user info, cert paths) must ALWAYS be
# supplied at runtime via --env-file or the environment: section in
# docker-compose.yml — never hard-code them here.

# Ports
ENV QLIK_REPOSITORY_PORT="4242"
ENV QLIK_PROXY_PORT="4243"
ENV QLIK_ENGINE_PORT="4747"

# SSL
ENV QLIK_VERIFY_SSL="true"

# Logging  (DEBUG | INFO | WARNING | ERROR)
ENV LOG_LEVEL="INFO"

# The variables below are intentionally left empty so that Docker's secret
# linter does not flag path names containing "KEY".  Pass them at runtime:
#   QLIK_SERVER_URL, QLIK_USER_DIRECTORY, QLIK_USER_ID
#   QLIK_CLIENT_CERT_PATH, QLIK_CLIENT_KEY_PATH, QLIK_CA_CERT_PATH
#   QLIK_HTTP_PORT

# ── MCP uses stdio: the container must be run with -i (stdin open) ─────────────
# Remote gateway mode (`qlik-sense-mcp-gateway`) listens on TCP 8080.
EXPOSE 8080

ENTRYPOINT ["qlik-sense-mcp-server"]
