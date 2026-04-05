"""Tests for server module."""

import json
import pytest
from unittest.mock import patch, MagicMock
from mcp.types import CallToolRequest
from qlik_sense_mcp_server.server import _make_error, QlikSenseMCPServer
from qlik_sense_mcp_server import __version__


class TestMakeError:
    def test_basic_error(self):
        result = _make_error("something went wrong")
        assert result == {"error": "something went wrong"}

    def test_error_with_extras(self):
        result = _make_error("failed", app_id="abc-123", details="more info")
        assert result["error"] == "failed"
        assert result["app_id"] == "abc-123"
        assert result["details"] == "more info"

    def test_error_always_has_error_key(self):
        result = _make_error("test")
        assert "error" in result


class TestVersion:
    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_version_is_1_4_7(self):
        assert __version__ == "1.4.7"


class TestQlikSenseMCPServer:
    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "",
        "QLIK_USER_DIRECTORY": "",
        "QLIK_USER_ID": "",
    }, clear=False)
    def test_invalid_config(self):
        server = QlikSenseMCPServer()
        assert server.config_valid is False
        assert server.repository_api is None
        assert server.engine_api is None

    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    def test_valid_config_creates_apis(self):
        server = QlikSenseMCPServer()
        assert server.config_valid is True
        assert server.repository_api is not None
        assert server.engine_api is not None

    def test_validate_config_no_config(self):
        server = QlikSenseMCPServer.__new__(QlikSenseMCPServer)
        server.config = None
        assert server._validate_config() is False

    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
    }, clear=False)
    def test_server_has_server_instance(self):
        server = QlikSenseMCPServer()
        assert server.server is not None

    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    async def test_get_app_details_falls_back_to_engine_api_when_ticket_is_unavailable(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock(return_value={
            "id": "app-123",
            "name": "Demo App",
            "description": "demo",
            "published": True,
            "stream": {"name": "Everyone"},
            "modifiedDate": "2026-04-05T00:00:00Z",
            "lastReloadTime": "2026-04-05T00:00:00Z",
        })
        server._get_qlik_ticket = MagicMock(return_value=None)
        server._get_app_metadata_via_proxy = MagicMock()
        server.engine_api.get_detailed_app_metadata = MagicMock(return_value={
            "fields": [{"name": "Customer"}],
            "tables": [{"name": "Facts"}],
        })

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(params={"name": "get_app_details", "arguments": {"app_id": "app-123"}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["metainfo"]["app_id"] == "app-123"
        assert payload["fields"] == [{"name": "Customer"}]
        assert payload["tables"] == [{"name": "Facts"}]
        server._get_app_metadata_via_proxy.assert_not_called()
        server.engine_api.get_detailed_app_metadata.assert_called_once_with("app-123")

    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    async def test_get_app_details_accepts_appid_alias(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock(return_value={
            "id": "app-123",
            "name": "Demo App",
            "description": "demo",
            "published": True,
            "stream": {"name": "Everyone"},
            "modifiedDate": "2026-04-05T00:00:00Z",
            "lastReloadTime": "2026-04-05T00:00:00Z",
        })
        server._get_qlik_ticket = MagicMock(return_value=None)
        server._get_app_metadata_via_proxy = MagicMock()
        server.engine_api.get_detailed_app_metadata = MagicMock(return_value={
            "fields": [{"name": "Customer"}],
            "tables": [{"name": "Facts"}],
        })

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(params={"name": "get_app_details", "arguments": {"appId": "app-123"}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["metainfo"]["app_id"] == "app-123"
        server.repository_api.get_app_by_id.assert_called_once_with("app-123")

    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    async def test_get_apps_my_work_returns_unpublished(self):
        server = QlikSenseMCPServer()
        mock_payload = {
            "apps": [{"guid": "app-x", "name": "Personal App", "description": "", "stream": "My Work", "modified_dttm": "", "reload_dttm": ""}],
            "pagination": {"limit": 20, "offset": 0, "returned": 1, "total_found": 1, "has_more": False, "next_offset": None},
        }
        server.repository_api.get_comprehensive_apps = MagicMock(return_value=mock_payload)

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(params={"name": "get_apps", "arguments": {"stream": "My Work"}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["apps"][0]["stream"] == "My Work"
        server.repository_api.get_comprehensive_apps.assert_called_once()
        call_kwargs = server.repository_api.get_comprehensive_apps.call_args
        assert call_kwargs.kwargs.get("stream") == "My Work" or call_kwargs.args[3] == "My Work"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    async def test_get_apps_my_work_case_insensitive(self):
        server = QlikSenseMCPServer()
        mock_payload = {
            "apps": [{"guid": "app-y", "name": "Another Personal", "description": "", "stream": "My Work", "modified_dttm": "", "reload_dttm": ""}],
            "pagination": {"limit": 20, "offset": 0, "returned": 1, "total_found": 1, "has_more": False, "next_offset": None},
        }
        server.repository_api.get_comprehensive_apps = MagicMock(return_value=mock_payload)

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(params={"name": "get_apps", "arguments": {"stream": "my work"}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["apps"][0]["stream"] == "My Work"
        server.repository_api.get_comprehensive_apps.assert_called_once()
        call_kwargs = server.repository_api.get_comprehensive_apps.call_args
        assert call_kwargs.kwargs.get("stream") == "my work" or call_kwargs.args[3] == "my work"
