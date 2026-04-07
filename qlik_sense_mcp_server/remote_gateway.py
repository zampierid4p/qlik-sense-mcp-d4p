"""Remote HTTP gateway for Qlik Sense MCP server with token authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
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

_STARTUP_ENV_KEYS = (
    "QLIK_SERVER_URL",
    "QLIK_USER_DIRECTORY",
    "QLIK_USER_ID",
    "QLIK_CLIENT_CERT_PATH",
    "QLIK_CLIENT_KEY_PATH",
    "QLIK_CA_CERT_PATH",
    "QLIK_REPOSITORY_PORT",
    "QLIK_PROXY_PORT",
    "QLIK_ENGINE_PORT",
    "QLIK_HTTP_PORT",
    "QLIK_VERIFY_SSL",
    "MCP_GATEWAY_HOST",
    "MCP_GATEWAY_PORT",
    "MCP_PUBLIC_PORT",
    "MCP_GATEWAY_PATH",
    "MCP_AUTH_MODE",
    "MCP_AUTH_TOKEN",
    "MCP_AUTH_PASSPHRASE",
    "MCP_JWT_SECRET",
    "MCP_JWT_AUDIENCE",
    "MCP_JWT_ISSUER",
    "LOG_LEVEL",
)

_SENSITIVE_ENV_TOKENS = ("TOKEN", "PASSPHRASE", "SECRET", "KEY", "PASSWORD")
_CERT_PATH_KEYS = {
    "QLIK_CLIENT_CERT_PATH",
    "QLIK_CLIENT_KEY_PATH",
    "QLIK_CA_CERT_PATH",
}


def _normalize_path(path: str) -> str:
    """Normalize endpoint path to a slash-prefixed route."""
    return GatewayConfig.model_fields["path"].default if not path else GatewayConfig(path=path, auth_token="placeholder").path


def _normalize_env_value(value: object) -> str:
    """Normalize environment values for stable startup logging."""
    if value is None:
        return "<unset>"
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else "<empty>"
    return str(value)


def _is_sensitive_env_key(env_key: str) -> bool:
    """Return True when the key should be redacted in startup logs."""
    upper_key = env_key.upper()
    if upper_key in _CERT_PATH_KEYS:
        return False
    return any(token in upper_key for token in _SENSITIVE_ENV_TOKENS)


def _redact_env_value(env_key: str, value: object) -> str:
    """Redact sensitive startup env values while preserving empty/unset states."""
    normalized = _normalize_env_value(value)
    if _is_sensitive_env_key(env_key) and normalized not in {"<unset>", "<empty>"}:
        return "***redacted***"
    return normalized


def _build_startup_environment_snapshot(
    gateway_config: GatewayConfig,
    qlik_config: QlikSenseConfig,
) -> dict[str, str]:
    """Build startup env snapshot with sensitive values safely redacted."""
    resolved_values: dict[str, object] = {
        "QLIK_SERVER_URL": qlik_config.server_url,
        "QLIK_USER_DIRECTORY": qlik_config.user_directory,
        "QLIK_USER_ID": qlik_config.user_id,
        "QLIK_CLIENT_CERT_PATH": qlik_config.client_cert_path,
        "QLIK_CLIENT_KEY_PATH": qlik_config.client_key_path,
        "QLIK_CA_CERT_PATH": qlik_config.ca_cert_path,
        "QLIK_REPOSITORY_PORT": qlik_config.repository_port,
        "QLIK_PROXY_PORT": qlik_config.proxy_port,
        "QLIK_ENGINE_PORT": qlik_config.engine_port,
        "QLIK_HTTP_PORT": qlik_config.http_port,
        "QLIK_VERIFY_SSL": qlik_config.verify_ssl,
        "MCP_GATEWAY_HOST": gateway_config.host,
        "MCP_GATEWAY_PORT": gateway_config.port,
        "MCP_PUBLIC_PORT": gateway_config.public_port,
        "MCP_GATEWAY_PATH": gateway_config.path,
        "MCP_AUTH_MODE": gateway_config.auth_mode,
        "MCP_AUTH_TOKEN": gateway_config.auth_token,
        "MCP_AUTH_PASSPHRASE": gateway_config.auth_passphrase,
        "MCP_JWT_SECRET": gateway_config.jwt_secret,
        "MCP_JWT_AUDIENCE": gateway_config.jwt_audience,
        "MCP_JWT_ISSUER": gateway_config.jwt_issuer,
        "LOG_LEVEL": gateway_config.log_level,
    }

    snapshot: dict[str, str] = {}
    for key in _STARTUP_ENV_KEYS:
        snapshot[key] = _redact_env_value(key, resolved_values.get(key, os.getenv(key)))
    return snapshot


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


def _b64url_decode(value: str) -> bytes:
    """Decode a base64url string with optional stripped padding."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _is_valid_jwt_hs256(
    token: str,
    secret: Optional[str],
    audience: Optional[str] = None,
    issuer: Optional[str] = None,
) -> bool:
    """Validate HS256 JWT signature and standard claims."""
    if not secret:
        return False

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False

        header_b64, payload_b64, signature_b64 = parts
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        if header.get("alg") != "HS256":
            return False

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            return False

        now = int(time.time())
        exp = payload.get("exp")
        if exp is not None and now >= int(exp):
            return False

        nbf = payload.get("nbf")
        if nbf is not None and now < int(nbf):
            return False

        if issuer and payload.get("iss") != issuer:
            return False

        if audience:
            aud = payload.get("aud")
            if isinstance(aud, str):
                if aud != audience:
                    return False
            elif isinstance(aud, list):
                if audience not in aud:
                    return False
            else:
                return False

        return True
    except Exception:
        return False


def _is_authorized(
    request: Request,
    valid_tokens: Set[str],
    auth_mode: str = "token",
    jwt_secret: Optional[str] = None,
    jwt_audience: Optional[str] = None,
    jwt_issuer: Optional[str] = None,
) -> bool:
    """Validate request token against configured tokens."""
    request_token = _extract_token(request)
    if not request_token:
        return False

    token_allowed = auth_mode in {"token", "both"} and bool(valid_tokens and request_token in valid_tokens)
    jwt_allowed = auth_mode in {"jwt", "both"} and _is_valid_jwt_hs256(
        request_token,
        jwt_secret,
        audience=jwt_audience,
        issuer=jwt_issuer,
    )

    return token_allowed or jwt_allowed


class AuthenticatedMCPASGI:
    """ASGI wrapper that enforces token auth before forwarding to MCP manager."""

    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        valid_tokens: Set[str],
        auth_mode: str = "token",
        jwt_secret: Optional[str] = None,
        jwt_audience: Optional[str] = None,
        jwt_issuer: Optional[str] = None,
    ):
        self.manager = manager
        self.valid_tokens = valid_tokens
        self.auth_mode = auth_mode
        self.jwt_secret = jwt_secret
        self.jwt_audience = jwt_audience
        self.jwt_issuer = jwt_issuer

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)

        if not _is_authorized(
            request,
            self.valid_tokens,
            auth_mode=self.auth_mode,
            jwt_secret=self.jwt_secret,
            jwt_audience=self.jwt_audience,
            jwt_issuer=self.jwt_issuer,
        ):
            response = JSONResponse(
                {
                    "error": "unauthorized",
                    "message": "Provide Authorization: Bearer <token> or X-MCP-Token header (token or JWT based on gateway config)",
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
            "auth_mode": gateway_config.auth_mode,
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
    startup_environment = _build_startup_environment_snapshot(gateway_config, qlik_config)
    logger.info("Starting qlik-sense-mcp-gateway version=%s", __version__)
    logger.info(
        "Validated remote gateway config host=%s port=%s public_port=%s path=%s auth_configured=%s",
        gateway_config.host,
        gateway_config.port,
        gateway_config.public_port,
        gateway_config.path,
        True,
    )
    logger.info("Startup environment parameters: startup_environment=%s", startup_environment)
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

    auth_mcp_asgi = AuthenticatedMCPASGI(
        session_manager,
        gateway_config.auth_tokens,
        auth_mode=gateway_config.auth_mode,
        jwt_secret=gateway_config.jwt_secret,
        jwt_audience=gateway_config.jwt_audience,
        jwt_issuer=gateway_config.jwt_issuer,
    )

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
    MCP_AUTH_TOKEN or MCP_AUTH_PASSPHRASE - Token for Bearer authentication (token mode)
    QLIK_SERVER_URL                        - Qlik Sense server URL
    QLIK_USER_DIRECTORY                    - Qlik user directory
    QLIK_USER_ID                           - Qlik user ID
    QLIK_CLIENT_CERT_PATH                  - Path to client certificate
    QLIK_CLIENT_KEY_PATH                   - Path to client key
    QLIK_CA_CERT_PATH                      - Path to CA certificate

OPTIONAL ENVIRONMENT:
    MCP_AUTH_MODE                          - token (default), jwt, or both
    MCP_JWT_SECRET                         - HS256 secret for JWT validation
    MCP_JWT_AUDIENCE                       - Expected JWT aud claim (optional)
    MCP_JWT_ISSUER                         - Expected JWT iss claim (optional)
    MCP_GATEWAY_HOST                       - Listen host (default: 0.0.0.0)
    MCP_GATEWAY_PORT                       - Listen port (default: 8080)
    MCP_GATEWAY_PATH                       - MCP endpoint path (default: /mcp)
"""
    sys.stderr.write(help_text + "\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
