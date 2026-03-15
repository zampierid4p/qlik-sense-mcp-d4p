"""Tests for remote gateway helpers."""

from unittest.mock import patch

from starlette.requests import Request

from qlik_sense_mcp_server.remote_gateway import (
    _extract_token,
    _get_auth_tokens_from_env,
    _is_authorized,
    _normalize_path,
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


class TestPathNormalization:
    def test_empty_path_defaults_to_mcp(self):
        assert _normalize_path("") == "/mcp"

    def test_path_without_prefix_gets_slash(self):
        assert _normalize_path("mcp") == "/mcp"

    def test_path_with_prefix_is_kept(self):
        assert _normalize_path("/gateway") == "/gateway"


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
