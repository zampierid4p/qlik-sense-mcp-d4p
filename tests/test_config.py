"""Tests for configuration module."""

import os
import pytest
from unittest.mock import patch
from pydantic import ValidationError

from qlik_sense_mcp_server.config import (
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PATH,
    DEFAULT_GATEWAY_PORT,
    QlikSenseConfig,
    GatewayConfig,
    normalize_server_url,
    DEFAULT_REPOSITORY_PORT,
    DEFAULT_PROXY_PORT,
    DEFAULT_ENGINE_PORT,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_WS_TIMEOUT,
    DEFAULT_WS_RETRIES,
    DEFAULT_APPS_LIMIT,
    MAX_APPS_LIMIT,
    DEFAULT_FIELD_LIMIT,
    MAX_FIELD_LIMIT,
    DEFAULT_HYPERCUBE_MAX_ROWS,
    DEFAULT_FIELD_FETCH_SIZE,
    MAX_FIELD_FETCH_SIZE,
    MAX_TABLES_AND_KEYS_DIM,
    MAX_TABLES,
)


class TestConstants:
    def test_default_ports(self):
        assert DEFAULT_REPOSITORY_PORT == 4242
        assert DEFAULT_PROXY_PORT == 4243
        assert DEFAULT_ENGINE_PORT == 4747

    def test_default_timeouts(self):
        assert DEFAULT_HTTP_TIMEOUT == 10.0
        assert DEFAULT_WS_TIMEOUT == 8.0

    def test_default_retries(self):
        assert DEFAULT_WS_RETRIES == 2

    def test_pagination_limits(self):
        assert DEFAULT_APPS_LIMIT == 25
        assert MAX_APPS_LIMIT == 50
        assert DEFAULT_FIELD_LIMIT == 10
        assert MAX_FIELD_LIMIT == 100

    def test_hypercube_defaults(self):
        assert DEFAULT_HYPERCUBE_MAX_ROWS == 1000

    def test_fetch_sizes(self):
        assert DEFAULT_FIELD_FETCH_SIZE == 500
        assert MAX_FIELD_FETCH_SIZE == 5000

    def test_data_model_limits(self):
        assert MAX_TABLES_AND_KEYS_DIM == 1000
        assert MAX_TABLES == 50


class TestQlikSenseConfig:
    def test_required_fields(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com",
            user_directory="DOMAIN",
            user_id="admin",
        )
        assert config.server_url == "https://qlik.example.com"
        assert config.user_directory == "DOMAIN"
        assert config.user_id == "admin"

    def test_default_ports(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com",
            user_directory="DOMAIN",
            user_id="admin",
        )
        assert config.repository_port == DEFAULT_REPOSITORY_PORT
        assert config.proxy_port == DEFAULT_PROXY_PORT
        assert config.engine_port == DEFAULT_ENGINE_PORT

    def test_optional_fields_defaults(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com",
            user_directory="DOMAIN",
            user_id="admin",
        )
        assert config.client_cert_path is None
        assert config.client_key_path is None
        assert config.ca_cert_path is None
        assert config.http_port is None
        assert config.verify_ssl is True

    def test_custom_ports(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com",
            user_directory="DOMAIN",
            user_id="admin",
            repository_port=5555,
            engine_port=6666,
        )
        assert config.repository_port == 5555
        assert config.engine_port == 6666

    def test_ssl_disabled(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com",
            user_directory="DOMAIN",
            user_id="admin",
            verify_ssl=False,
        )
        assert config.verify_ssl is False

    @patch.dict(os.environ, {
        "QLIK_SERVER_URL": "https://test-server.com",
        "QLIK_USER_DIRECTORY": "TEST",
        "QLIK_USER_ID": "testuser",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_ENGINE_PORT": "9999",
    }, clear=False)
    def test_from_env(self):
        config = QlikSenseConfig.from_env()
        assert config.server_url == "https://test-server.com"
        assert config.user_directory == "TEST"
        assert config.user_id == "testuser"
        assert config.verify_ssl is False
        assert config.engine_port == 9999

    @patch.dict(os.environ, {
        "QLIK_SERVER_URL": "",
        "QLIK_USER_DIRECTORY": "",
        "QLIK_USER_ID": "",
    }, clear=False)
    def test_from_env_empty_strings_raise_validation_error(self):
        with pytest.raises(ValidationError):
            QlikSenseConfig.from_env()

    @patch.dict(os.environ, {
        "QLIK_SERVER_URL": "https://test.com",
        "QLIK_USER_DIRECTORY": "DIR",
        "QLIK_USER_ID": "user",
        "QLIK_HTTP_PORT": "443",
    }, clear=False)
    def test_from_env_http_port(self):
        config = QlikSenseConfig.from_env()
        assert config.http_port == 443

    def test_server_url_rejects_non_http_scheme(self):
        with pytest.raises(ValidationError):
            QlikSenseConfig(
                server_url="ftp://qlik.example.com",
                user_directory="DOMAIN",
                user_id="admin",
            )

    def test_server_url_normalizes_extra_path(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com/ticket/",
            user_directory="DOMAIN",
            user_id="admin",
        )
        assert config.server_url == "https://qlik.example.com"

    def test_server_url_normalizes_explicit_port(self):
        config = QlikSenseConfig(
            server_url="https://qlik.example.com:443/custom/path?x=1",
            user_directory="DOMAIN",
            user_id="admin",
        )
        assert config.server_url == "https://qlik.example.com"


class TestNormalizeServerUrl:
    def test_normalize_server_url_rejects_missing_host(self):
        with pytest.raises(ValueError):
            normalize_server_url("https:///missing-host")

    def test_normalize_server_url_strips_query_and_fragment(self):
        assert (
            normalize_server_url("https://qlik.example.com/base?ticket=1#frag")
            == "https://qlik.example.com"
        )


class TestGatewayConfig:
    @patch.dict(os.environ, {
        "MCP_AUTH_TOKEN": "token123",
    }, clear=True)
    def test_gateway_config_from_env_defaults(self):
        config = GatewayConfig.from_env()
        assert config.host == DEFAULT_GATEWAY_HOST
        assert config.port == DEFAULT_GATEWAY_PORT
        assert config.public_port == DEFAULT_GATEWAY_PORT
        assert config.path == DEFAULT_GATEWAY_PATH
        assert config.auth_tokens == {"token123"}

    @patch.dict(os.environ, {
        "MCP_AUTH_PASSPHRASE": "secret",
        "MCP_GATEWAY_PATH": "//nested//gateway//",
        "MCP_GATEWAY_PORT": "9090",
        "MCP_PUBLIC_PORT": "19090",
    }, clear=True)
    def test_gateway_config_normalizes_path_and_ports(self):
        config = GatewayConfig.from_env()
        assert config.path == "/nested/gateway"
        assert config.port == 9090
        assert config.public_port == 19090
        assert config.auth_tokens == {"secret"}

    @patch.dict(os.environ, {}, clear=True)
    def test_gateway_config_requires_auth(self):
        with pytest.raises(ValidationError):
            GatewayConfig.from_env()

    @patch.dict(os.environ, {
        "MCP_AUTH_TOKEN": "token123",
        "MCP_GATEWAY_PORT": "70000",
    }, clear=True)
    def test_gateway_config_rejects_port_out_of_range(self):
        with pytest.raises(ValidationError):
            GatewayConfig.from_env()
