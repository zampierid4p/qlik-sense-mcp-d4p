"""Configuration for Qlik Sense MCP Server."""

import errno
import os
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


# Default ports
DEFAULT_REPOSITORY_PORT = 4242
DEFAULT_PROXY_PORT = 4243
DEFAULT_ENGINE_PORT = 4747
DEFAULT_GATEWAY_HOST = "0.0.0.0"
DEFAULT_GATEWAY_PORT = 8080
DEFAULT_GATEWAY_PATH = "/mcp"

# Default timeouts (seconds)
DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_WS_TIMEOUT = 8.0
DEFAULT_TICKET_TIMEOUT = 30.0

# Default retry settings
DEFAULT_WS_RETRIES = 2

# Pagination defaults
DEFAULT_APPS_LIMIT = 25
MAX_APPS_LIMIT = 50
DEFAULT_FIELD_LIMIT = 10
MAX_FIELD_LIMIT = 100
DEFAULT_HYPERCUBE_MAX_ROWS = 1000

# Fetch sizes
DEFAULT_FIELD_FETCH_SIZE = 500
MAX_FIELD_FETCH_SIZE = 5000

# Data model limits
MAX_TABLES_AND_KEYS_DIM = 1000
MAX_TABLES = 50


def normalize_gateway_path(path: Optional[str]) -> str:
    """Normalize an MCP gateway path to a stable slash-prefixed route."""
    if path is None:
        return DEFAULT_GATEWAY_PATH

    stripped = path.strip()
    if not stripped or stripped.strip("/") == "":
        return DEFAULT_GATEWAY_PATH

    parts = [segment for segment in stripped.split("/") if segment]
    return "/" + "/".join(parts)


def normalize_server_url(value: str) -> str:
    """Normalize Qlik server URL to a bare origin without path, query, or fragment."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("QLIK_SERVER_URL is required")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("QLIK_SERVER_URL must be a valid http:// or https:// URL")

    host = parsed.hostname
    if not host:
        raise ValueError("QLIK_SERVER_URL must include a hostname")

    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    return f"{parsed.scheme}://{host}"


def validate_cert_file_paths(
    client_cert_path: Optional[str],
    client_key_path: Optional[str],
    ca_cert_path: Optional[str],
) -> None:
    """Validate certificate file paths when provided in configuration."""
    cert_fields = [
        ("QLIK_CLIENT_CERT_PATH", client_cert_path),
        ("QLIK_CLIENT_KEY_PATH", client_key_path),
        ("QLIK_CA_CERT_PATH", ca_cert_path),
    ]

    for env_name, path in cert_fields:
        if not path:
            continue
        if not os.path.isfile(path):
            raise FileNotFoundError(
                errno.ENOENT,
                f"{env_name} points to a missing file",
                path,
            )


class QlikSenseConfig(BaseModel):
    """
    Configuration model for Qlik Sense Enterprise server connection.

    Handles server connection details, authentication credentials,
    certificate paths, and API endpoint configuration.
    """

    server_url: str = Field(..., description="Qlik Sense server URL (e.g., https://qlik.company.com)")
    user_directory: str = Field(..., description="User directory for authentication")
    user_id: str = Field(..., description="User ID for authentication")
    client_cert_path: Optional[str] = Field(None, description="Path to client certificate")
    client_key_path: Optional[str] = Field(None, description="Path to client private key")
    ca_cert_path: Optional[str] = Field(None, description="Path to CA certificate")
    repository_port: int = Field(DEFAULT_REPOSITORY_PORT, description="Repository API port")
    proxy_port: int = Field(DEFAULT_PROXY_PORT, description="Proxy API port")
    engine_port: int = Field(DEFAULT_ENGINE_PORT, description="Engine API port")
    http_port: Optional[int] = Field(None, description="HTTP API port for metadata requests")
    verify_ssl: bool = Field(True, description="Verify SSL certificates")

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        """Ensure Qlik URL is a non-empty HTTP(S) URL."""
        return normalize_server_url(value)

    @field_validator("user_directory", "user_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Ensure required text settings are not empty."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Configuration value cannot be empty")
        return normalized

    def validate_runtime(self) -> None:
        """Validate runtime dependencies required to serve requests."""
        validate_cert_file_paths(
            self.client_cert_path,
            self.client_key_path,
            self.ca_cert_path,
        )

    @classmethod
    def from_env(cls) -> "QlikSenseConfig":
        """
        Create configuration instance from environment variables.

        Reads all required and optional configuration values from environment
        variables with QLIK_ prefix and validates them.

        Returns:
            Configured QlikSenseConfig instance
        """
        return cls(
            server_url=os.getenv("QLIK_SERVER_URL", ""),
            user_directory=os.getenv("QLIK_USER_DIRECTORY", ""),
            user_id=os.getenv("QLIK_USER_ID", ""),
            client_cert_path=os.getenv("QLIK_CLIENT_CERT_PATH"),
            client_key_path=os.getenv("QLIK_CLIENT_KEY_PATH"),
            ca_cert_path=os.getenv("QLIK_CA_CERT_PATH"),
            repository_port=int(os.getenv("QLIK_REPOSITORY_PORT", str(DEFAULT_REPOSITORY_PORT))),
            proxy_port=int(os.getenv("QLIK_PROXY_PORT", str(DEFAULT_PROXY_PORT))),
            engine_port=int(os.getenv("QLIK_ENGINE_PORT", str(DEFAULT_ENGINE_PORT))),
            http_port=int(os.getenv("QLIK_HTTP_PORT")) if os.getenv("QLIK_HTTP_PORT") else None,
            verify_ssl=os.getenv("QLIK_VERIFY_SSL", "true").lower() == "true"
        )


class GatewayConfig(BaseModel):
    """Configuration for the remote HTTP MCP gateway."""

    host: str = Field(DEFAULT_GATEWAY_HOST, description="Gateway listen host")
    port: int = Field(DEFAULT_GATEWAY_PORT, ge=1, le=65535, description="Gateway listen port")
    public_port: int = Field(
        DEFAULT_GATEWAY_PORT,
        ge=1,
        le=65535,
        description="Host port published by Docker or reverse proxy",
    )
    path: str = Field(DEFAULT_GATEWAY_PATH, description="Gateway MCP route path")
    auth_token: Optional[str] = Field(None, description="Bearer token for remote clients")
    auth_passphrase: Optional[str] = Field(None, description="Fallback remote credential")
    auth_mode: str = Field("token", description="Gateway auth mode: token, jwt, both")
    jwt_secret: Optional[str] = Field(None, description="HS256 secret for JWT validation")
    jwt_audience: Optional[str] = Field(None, description="Expected JWT audience (optional)")
    jwt_issuer: Optional[str] = Field(None, description="Expected JWT issuer (optional)")
    log_level: str = Field("INFO", description="Gateway log level")

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MCP_GATEWAY_HOST cannot be empty")
        return normalized

    @field_validator("path", mode="before")
    @classmethod
    def validate_path(cls, value: Optional[str]) -> str:
        return normalize_gateway_path(value)

    @field_validator("auth_token", "auth_passphrase", mode="before")
    @classmethod
    def normalize_secret(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("auth_mode")
    @classmethod
    def normalize_auth_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"token", "jwt", "both"}:
            raise ValueError("MCP_AUTH_MODE must be one of: token, jwt, both")
        return normalized

    @field_validator("jwt_secret", "jwt_audience", "jwt_issuer", mode="before")
    @classmethod
    def normalize_jwt_fields(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("LOG_LEVEL cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_auth(self) -> "GatewayConfig":
        token_available = bool(self.auth_token or self.auth_passphrase)
        jwt_available = bool(self.jwt_secret)

        if self.auth_mode == "token" and not token_available:
            raise ValueError(
                "Remote gateway requires MCP_AUTH_TOKEN or MCP_AUTH_PASSPHRASE to be set"
            )
        if self.auth_mode == "jwt" and not jwt_available:
            raise ValueError("Remote gateway with MCP_AUTH_MODE=jwt requires MCP_JWT_SECRET")
        if self.auth_mode == "both" and not (token_available or jwt_available):
            raise ValueError(
                "Remote gateway with MCP_AUTH_MODE=both requires token/passphrase or MCP_JWT_SECRET"
            )
        return self

    @property
    def auth_tokens(self) -> set[str]:
        """Return all accepted remote authentication values."""
        tokens: set[str] = set()
        if self.auth_token:
            tokens.add(self.auth_token)
        if self.auth_passphrase:
            tokens.add(self.auth_passphrase)
        return tokens

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Create gateway configuration from environment variables."""
        return cls(
            host=os.getenv("MCP_GATEWAY_HOST", DEFAULT_GATEWAY_HOST),
            port=os.getenv("MCP_GATEWAY_PORT", str(DEFAULT_GATEWAY_PORT)),
            public_port=os.getenv("MCP_PUBLIC_PORT", os.getenv("MCP_GATEWAY_PORT", str(DEFAULT_GATEWAY_PORT))),
            path=os.getenv("MCP_GATEWAY_PATH", DEFAULT_GATEWAY_PATH),
            auth_token=os.getenv("MCP_AUTH_TOKEN"),
            auth_passphrase=os.getenv("MCP_AUTH_PASSPHRASE"),
            auth_mode=os.getenv("MCP_AUTH_MODE", "token"),
            jwt_secret=os.getenv("MCP_JWT_SECRET"),
            jwt_audience=os.getenv("MCP_JWT_AUDIENCE"),
            jwt_issuer=os.getenv("MCP_JWT_ISSUER"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
