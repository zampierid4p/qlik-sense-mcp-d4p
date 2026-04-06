"""Tests for remote gateway helpers."""

import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from unittest.mock import patch

from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.testclient import TestClient

from qlik_sense_mcp_server.remote_gateway import (
    _extract_token,
    _get_auth_tokens_from_env,
    _is_authorized,
    _normalize_path,
    create_gateway_app,
)


def _make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8080),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _make_hs256_jwt(payload: dict[str, object], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.{signature_b64}"


class TestPathNormalization:
    def test_empty_path_defaults_to_mcp(self):
        assert _normalize_path("") == "/mcp"

    def test_path_without_prefix_gets_slash(self):
        assert _normalize_path("mcp") == "/mcp"

    def test_path_with_prefix_is_kept(self):
        assert _normalize_path("/gateway") == "/gateway"

    def test_path_collapses_duplicate_slashes(self):
        assert _normalize_path("//gateway//nested//") == "/gateway/nested"


class TestTokenConfig:
    @patch.dict("os.environ", {"MCP_AUTH_TOKEN": "token123", "MCP_AUTH_PASSPHRASE": "phrase456"}, clear=False)
    def test_tokens_loaded_from_env(self):
        tokens = _get_auth_tokens_from_env()
        assert "token123" in tokens
        assert "phrase456" in tokens


class TestAuthExtraction:
    def test_extract_from_bearer_header(self):
        req = _make_request({"authorization": "Bearer abc123"})
        assert _extract_token(req) == "abc123"

    def test_extract_from_x_mcp_token_header(self):
        req = _make_request({"x-mcp-token": "secret-token"})
        assert _extract_token(req) == "secret-token"

    def test_is_authorized_true_when_token_matches(self):
        req = _make_request({"authorization": "Bearer allow-me"})
        assert _is_authorized(req, {"allow-me"}) is True

    def test_is_authorized_false_when_missing(self):
        req = _make_request({})
        assert _is_authorized(req, {"allow-me"}) is False


class _FakeQlikServer:
    def __init__(self):
        self.server = object()


class _FakeSessionManager:
    def __init__(self, app, json_response, stateless):
        self.app = app
        self.json_response = json_response
        self.stateless = stateless

    @asynccontextmanager
    async def run(self):
        yield

    async def handle_request(self, scope, receive, send):
        response = JSONResponse({"handled": True, "path": scope.get("path")})
        await response(scope, receive, send)


def _make_client(monkeypatch, extra_env: dict[str, str] | None = None) -> TestClient:
    env = {
        "MCP_AUTH_TOKEN": "token123",
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
    }
    if extra_env:
        env.update(extra_env)

    monkeypatch.setattr("qlik_sense_mcp_server.remote_gateway.load_dotenv", lambda: None)
    monkeypatch.setattr("qlik_sense_mcp_server.remote_gateway.QlikSenseMCPServer", _FakeQlikServer)
    monkeypatch.setattr(
        "qlik_sense_mcp_server.remote_gateway.StreamableHTTPSessionManager",
        _FakeSessionManager,
    )

    with patch.dict("os.environ", env, clear=True):
        app = create_gateway_app()
    return TestClient(app)


class TestGatewayHttp:
    def test_root_health_and_readiness(self, monkeypatch):
        client = _make_client(monkeypatch)

        root_response = client.get("/")
        assert root_response.status_code == 200
        assert "MCP endpoint: /mcp" in root_response.text
        assert "Readiness endpoint: /readyz" in root_response.text

        health_response = client.get("/healthz")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "ok"

        ready_response = client.get("/readyz")
        assert ready_response.status_code == 200
        payload = ready_response.json()
        assert payload["status"] == "ready"
        assert payload["gateway"]["path"] == "/mcp"
        assert payload["gateway"]["auth_configured"] is True

    def test_mcp_requires_authentication(self, monkeypatch):
        client = _make_client(monkeypatch)
        response = client.get("/mcp/")
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    def test_mcp_accepts_bearer_token(self, monkeypatch):
        client = _make_client(monkeypatch)
        response = client.get("/mcp/", headers={"Authorization": "Bearer token123"})
        assert response.status_code == 200
        assert response.json()["handled"] is True

    def test_custom_path_is_normalized(self, monkeypatch):
        client = _make_client(monkeypatch, {"MCP_GATEWAY_PATH": "//custom//mcp//"})
        response = client.get("/custom/mcp/", headers={"X-MCP-Token": "token123"})
        assert response.status_code == 200
        ready_response = client.get("/readyz")
        assert ready_response.json()["gateway"]["path"] == "/custom/mcp"

    def test_mcp_accepts_jwt_when_mode_is_jwt(self, monkeypatch):
        client = _make_client(
            monkeypatch,
            {
                "MCP_AUTH_MODE": "jwt",
                "MCP_JWT_SECRET": "super-secret",
            },
        )

        token = _make_hs256_jwt({"sub": "tester", "exp": int(time.time()) + 60}, "super-secret")
        response = client.get("/mcp/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["handled"] is True

    def test_mcp_rejects_expired_jwt(self, monkeypatch):
        client = _make_client(
            monkeypatch,
            {
                "MCP_AUTH_MODE": "jwt",
                "MCP_JWT_SECRET": "super-secret",
            },
        )

        token = _make_hs256_jwt({"sub": "tester", "exp": int(time.time()) - 60}, "super-secret")
        response = client.get("/mcp/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
