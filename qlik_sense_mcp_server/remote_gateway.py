"""Remote HTTP gateway for Qlik Sense MCP server with token authentication."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional, Set

import uvicorn
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.applications import Starlette

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from . import __version__
from .config import GatewayConfig, QlikSenseConfig
from .server import QlikSenseMCPServer

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """Normalize endpoint path to a slash-prefixed route."""
    return GatewayConfig.model_fields["path"].default if not path else GatewayConfig(path=path, auth_token="placeholder").path


def _get_auth_tokens_from_env() -> Set[str]:
    """Read accepted bearer tokens from environment variables."""
    tokens: Set[str] = set()
    token = os.getenv("MCP_AUTH_TOKEN", "").strip()
    passphrase = os.getenv("MCP_AUTH_PASSPHRASE", "").strip()

    if token:
        tokens.add(token)
    if passphrase:
        tokens.add(passphrase)

    return tokens


def _extract_token(request: Request) -> Optional[str]:
    """Extract auth token from Authorization or X-MCP-Token headers."""
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
        if candidate:
            return candidate

    x_token = request.headers.get("x-mcp-token", "").strip()
    if x_token:
        return x_token

    return None


def _is_authorized(request: Request, valid_tokens: Set[str]) -> bool:
    """Validate request token against configured tokens."""
    if not valid_tokens:
        return False
    request_token = _extract_token(request)
    return bool(request_token and request_token in valid_tokens)


class AuthenticatedMCPASGI:
    """ASGI wrapper that enforces token auth before forwarding to MCP manager."""

    def __init__(self, manager: StreamableHTTPSessionManager, valid_tokens: Set[str]):
        self.manager = manager
        self.valid_tokens = valid_tokens

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)

        if not _is_authorized(request, self.valid_tokens):
            response = JSONResponse(
                {
                    "error": "unauthorized",
                    "message": "Provide Authorization: Bearer <token> or X-MCP-Token header",
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.manager.handle_request(scope, receive, send)


def _build_startup_metadata(gateway_config: GatewayConfig, qlik_config: QlikSenseConfig) -> dict[str, object]:
    """Build a safe readiness payload without leaking secrets."""
    return {
        "status": "ready",
        "version": __version__,
        "transport": "streamable-http",
        "gateway": {
            "host": gateway_config.host,
            "port": gateway_config.port,
            "public_port": gateway_config.public_port,
            "path": gateway_config.path,
            "auth_configured": True,
        },
        "qlik": {
            "server_url": qlik_config.server_url,
            "user_directory": qlik_config.user_directory,
            "user_id": qlik_config.user_id,
            "certificates": {
                "client_cert": bool(qlik_config.client_cert_path),
                "client_key": bool(qlik_config.client_key_path),
                "ca_cert": bool(qlik_config.ca_cert_path),
            },
        },
    }


def _validate_startup(gateway_config: GatewayConfig) -> tuple[QlikSenseConfig, dict[str, object]]:
    """Validate gateway and Qlik runtime dependencies before binding the socket."""
    qlik_config = QlikSenseConfig.from_env()
    qlik_config.validate_runtime()
    startup_metadata = _build_startup_metadata(gateway_config, qlik_config)
    logger.info(
        "Validated remote gateway config host=%s port=%s public_port=%s path=%s auth_configured=%s",
        gateway_config.host,
        gateway_config.port,
        gateway_config.public_port,
        gateway_config.path,
        True,
    )
    return qlik_config, startup_metadata


def create_gateway_app(gateway_config: Optional[GatewayConfig] = None) -> Starlette:
    """Create Starlette app exposing MCP over Streamable HTTP with token auth."""
    load_dotenv()

    gateway_config = gateway_config or GatewayConfig.from_env()
    _qlik_config, startup_metadata = _validate_startup(gateway_config)

    qlik_server = QlikSenseMCPServer()
    session_manager = StreamableHTTPSessionManager(
        app=qlik_server.server,
        json_response=False,
        stateless=False,
    )

    auth_mcp_asgi = AuthenticatedMCPASGI(session_manager, gateway_config.auth_tokens)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with session_manager.run():
            yield

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "version": __version__, "transport": "streamable-http"})

    async def readyz(_request: Request) -> Response:
        return JSONResponse(startup_metadata)

    async def root(_request: Request) -> Response:
        return PlainTextResponse(
            "Qlik Sense MCP Remote Gateway\n"
            f"MCP endpoint: {gateway_config.path}\n"
            "Readiness endpoint: /readyz\n"
            "Auth: Bearer token required\n"
        )

    app = Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[
            Route("/", endpoint=root, methods=["GET"]),
            Route("/healthz", endpoint=healthz, methods=["GET"]),
            Route("/readyz", endpoint=readyz, methods=["GET"]),
            Mount(gateway_config.path, app=auth_mcp_asgi),
        ],
    )
    return app


def main() -> None:
    """CLI entrypoint for remote gateway mode."""
    load_dotenv()

    if len(sys.argv) > 1:
        if sys.argv[1] in ["--help", "-h"]:
            print_help()
            return
        if sys.argv[1] in ["--version", "-v"]:
            sys.stderr.write(f"qlik-sense-mcp-gateway {__version__}\n")
            sys.stderr.flush()
            return

    try:
        gateway_config = GatewayConfig.from_env()
        app = create_gateway_app(gateway_config)
    except Exception as exc:
        logger.error("Gateway startup validation failed: %s", exc)
        raise

    uvicorn.run(
        app,
        host=gateway_config.host,
        port=gateway_config.port,
        log_level=gateway_config.log_level.lower(),
    )


def print_help() -> None:
    """Print CLI help for remote gateway mode."""
    help_text = """
Qlik Sense MCP Remote Gateway

USAGE:
    qlik-sense-mcp-gateway [OPTIONS]

OPTIONS:
    -h, --help     Show this help message
    -v, --version  Show version information

REQUIRED ENVIRONMENT:
    MCP_AUTH_TOKEN or MCP_AUTH_PASSPHRASE - Token for Bearer authentication
    QLIK_SERVER_URL                        - Qlik Sense server URL
    QLIK_USER_DIRECTORY                    - Qlik user directory
    QLIK_USER_ID                           - Qlik user ID
    QLIK_CLIENT_CERT_PATH                  - Path to client certificate
    QLIK_CLIENT_KEY_PATH                   - Path to client key
    QLIK_CA_CERT_PATH                      - Path to CA certificate

OPTIONAL ENVIRONMENT:
    MCP_GATEWAY_HOST                       - Listen host (default: 0.0.0.0)
    MCP_GATEWAY_PORT                       - Listen port (default: 8080)
    MCP_GATEWAY_PATH                       - MCP endpoint path (default: /mcp)
"""
    sys.stderr.write(help_text + "\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
