"""Tests for server module."""

import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from mcp.types import CallToolRequest, ListToolsRequest
from qlik_sense_mcp_server.server import _make_error, QlikSenseMCPServer
from qlik_sense_mcp_server import __version__


TEST_APP_ID = "11111111-1111-1111-1111-111111111111"
RESOLVED_APP_ID = "22222222-2222-2222-2222-222222222222"


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

    def test_version_is_1_5_0(self):
        assert __version__ == "1.5.0"


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
            "id": TEST_APP_ID,
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
        result = await handler(CallToolRequest(params={"name": "get_app_details", "arguments": {"app_id": TEST_APP_ID}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["metainfo"]["app_id"] == TEST_APP_ID
        assert payload["fields"] == [{"name": "Customer"}]
        assert payload["tables"] == [{"name": "Facts"}]
        server._get_app_metadata_via_proxy.assert_not_called()
        server.engine_api.get_detailed_app_metadata.assert_called_once_with(TEST_APP_ID)

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
            "id": TEST_APP_ID,
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
        result = await handler(CallToolRequest(params={"name": "get_app_details", "arguments": {"appId": TEST_APP_ID}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["metainfo"]["app_id"] == TEST_APP_ID
        server.repository_api.get_app_by_id.assert_called_once_with(TEST_APP_ID)

    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    def test_resolve_app_id_passthrough_for_guid(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock()
        server.repository_api.get_comprehensive_apps = MagicMock()

        resolved = server._resolve_app_id(TEST_APP_ID)

        assert resolved == TEST_APP_ID
        server.repository_api.get_app_by_id.assert_not_called()
        server.repository_api.get_comprehensive_apps.assert_not_called()

    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    def test_resolve_app_id_resolves_by_name(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock(return_value={"error": "not found"})
        server.repository_api.get_comprehensive_apps = MagicMock(return_value={
            "apps": [
                {"guid": RESOLVED_APP_ID, "name": "Demo App"},
                {"guid": TEST_APP_ID, "name": "Demo App Copy"},
            ]
        })

        resolved = server._resolve_app_id("demo app")

        assert resolved == RESOLVED_APP_ID
        server.repository_api.get_comprehensive_apps.assert_called_once()

    @patch.dict("os.environ", {
        "QLIK_SERVER_URL": "https://qlik.example.com",
        "QLIK_USER_DIRECTORY": "DOMAIN",
        "QLIK_USER_ID": "admin",
        "QLIK_VERIFY_SSL": "false",
        "QLIK_CLIENT_CERT_PATH": "",
        "QLIK_CLIENT_KEY_PATH": "",
        "QLIK_CA_CERT_PATH": "",
    }, clear=False)
    def test_resolve_app_id_raises_if_not_found(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock(return_value={"error": "not found"})
        server.repository_api.get_comprehensive_apps = MagicMock(return_value={"apps": []})

        with pytest.raises(ValueError, match="App not found"):
            server._resolve_app_id("Missing App")

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
    async def test_get_app_sheets_accepts_app_name(self):
        server = QlikSenseMCPServer()
        server.repository_api.get_app_by_id = MagicMock(return_value={"error": "not found"})
        server.repository_api.get_comprehensive_apps = MagicMock(return_value={
            "apps": [{"guid": RESOLVED_APP_ID, "name": "Demo App"}]
        })
        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc_safe = MagicMock(return_value={"qReturn": {"qHandle": 321}})
        server.engine_api.get_sheets = MagicMock(return_value=[
            {"qInfo": {"qId": "sheet-1"}, "qMeta": {"title": "Overview", "description": "Main sheet"}}
        ])

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(params={"name": "get_app_sheets", "arguments": {"app_id": "Demo App"}}))
        payload = json.loads(result.root.content[0].text)

        assert payload["app_id"] == RESOLVED_APP_ID
        assert payload["total_sheets"] == 1
        server.engine_api.open_doc_safe.assert_called_once_with(RESOLVED_APP_ID, no_data=True)

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
    async def test_list_tools_includes_hidden_tools_now_public(self):
        server = QlikSenseMCPServer()

        handler = server.server.request_handlers[ListToolsRequest]
        result = await handler(ListToolsRequest())
        tools = {tool.name for tool in result.root.tools}
        tool_map = {tool.name: tool for tool in result.root.tools}

        assert "engine_get_chart_data" in tools
        assert "engine_export_visualization_to_csv" in tools
        assert "engine_export_visualization_to_xlsx" in tools
        assert "engine_export_visualization_to_pdf" in tools
        assert "engine_export_visualization_to_image" in tools
        assert "get_app_reload_chain" in tools

        get_apps_schema = tool_map["get_apps"].inputSchema
        assert get_apps_schema["properties"]["published"]["type"] == "boolean"
        assert get_apps_schema["properties"]["published"]["default"] is True

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
    async def test_get_visualization_image_returns_base64_payload(self):
        server = QlikSenseMCPServer()
        fake_bytes = b"\x89PNG\r\n\x1a\nFAKE"

        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        server.engine_api.get_visualization_image_reference = MagicMock(return_value={
            "object_id": "obj-1",
            "object_type": "barchart",
            "image_url": "/api/v1/fake/image.png",
        })
        server._download_binary_from_qlik = MagicMock(return_value={
            "content": fake_bytes,
            "content_type": "image/png",
            "download_url": "https://qlik.example.com/api/v1/fake/image.png",
        })

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                params={
                    "name": "get_visualization_image",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1", "format": "png"},
                }
            )
        )
        payload = json.loads(result.root.content[0].text)

        assert payload["app_id"] == TEST_APP_ID
        assert payload["object_id"] == "obj-1"
        assert payload["format"] == "png"
        assert payload["size_bytes"] == len(fake_bytes)
        assert base64.b64decode(payload["base64_image"]) == fake_bytes

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
    async def test_get_visualization_image_uses_headless_fallback_when_no_image_url(self):
        server = QlikSenseMCPServer()
        fake_bytes = b"\x89PNG\r\n\x1a\nFALLBACK"

        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        server.engine_api.get_visualization_image_reference = MagicMock(return_value={
            "error": "No image URL found for visualization",
            "object_id": "obj-1",
            "object_type": "linechart",
        })
        server._capture_visualization_image_headless = MagicMock(return_value={
            "content": fake_bytes,
            "content_type": "image/png",
            "source_url": f"https://qlik.example.com/single/?appid={TEST_APP_ID}&obj=obj-1",
        })

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                params={
                    "name": "get_visualization_image",
                    "arguments": {
                        "app_id": TEST_APP_ID,
                        "object_id": "obj-1",
                        "headless_fallback": True,
                    },
                }
            )
        )
        payload = json.loads(result.root.content[0].text)

        assert payload["used_headless_fallback"] is True
        assert payload["format"] == "png"
        assert payload["size_bytes"] == len(fake_bytes)
        assert base64.b64decode(payload["base64_image"]) == fake_bytes

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
    async def test_engine_export_visualization_to_csv_uses_exportdata_contract(self):
        server = QlikSenseMCPServer()
        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        server.engine_api.export_visualization_to_csv = MagicMock(return_value={"qUrl": "/temp/export.csv", "qWarnings": []})

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_csv",
                    "arguments": {
                        "app_id": TEST_APP_ID,
                        "object_id": "obj-1",
                        "q_path": "/qHyperCubeDef",
                        "q_export_state": "A",
                        "q_serve_once": False,
                    },
                }
            )
        )
        payload = json.loads(result.root.content[0].text)

        assert payload["format"] == "csv"
        assert payload["qUrl"] == "/temp/export.csv"
        server.engine_api.export_visualization_to_csv.assert_called_once_with(
            777,
            "obj-1",
            q_path="/qHyperCubeDef",
            q_export_state="A",
            q_serve_once=False,
        )

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
    async def test_engine_export_visualization_to_xlsx_pdf_image(self):
        server = QlikSenseMCPServer()
        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        server.engine_api.export_visualization_to_xlsx = MagicMock(return_value={"qUrl": "/temp/export.xlsx"})
        server.engine_api.export_visualization_to_pdf = MagicMock(return_value={"qUrl": "/temp/export.pdf"})
        server.engine_api.export_visualization_to_image = MagicMock(return_value={"qUrl": "/temp/export.png"})

        handler = server.server.request_handlers[CallToolRequest]

        xlsx_res = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_xlsx",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1"},
                }
            )
        )
        xlsx_payload = json.loads(xlsx_res.root.content[0].text)
        assert xlsx_payload["format"] == "xlsx"
        assert xlsx_payload["qUrl"] == "/temp/export.xlsx"

        pdf_res = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_pdf",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1"},
                }
            )
        )
        pdf_payload = json.loads(pdf_res.root.content[0].text)
        assert pdf_payload["format"] == "pdf"
        assert pdf_payload["qUrl"] == "/temp/export.pdf"

        img_res = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_image",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1"},
                }
            )
        )
        img_payload = json.loads(img_res.root.content[0].text)
        assert img_payload["format"] == "image"
        assert img_payload["qUrl"] == "/temp/export.png"

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
    async def test_engine_export_pdf_with_image_fallback_when_method_not_found(self):
        """Test PDF export fallback to image when ExportPdf not available."""
        server = QlikSenseMCPServer()
        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        
        # Mock ExportPdf to fail with Method not found
        server.engine_api.export_visualization_to_pdf = MagicMock(
            return_value={
                "qUrl": "/tempcontent/image.png",
                "qWarnings": ["ExportPdf not available; PNG export provided as fallback"],
                "fallback_format": "png",
            }
        )

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_pdf",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1"},
                }
            )
        )
        payload = json.loads(result.root.content[0].text)

        assert payload["qUrl"] == "/tempcontent/image.png"
        assert "ExportPdf not available" in str(payload.get("qWarnings", []))

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
    async def test_engine_export_image_with_layout_fallback_when_method_not_found(self):
        """Test image export fallback to layout extraction when ExportImg not available."""
        server = QlikSenseMCPServer()
        server.engine_api.connect = MagicMock()
        server.engine_api.disconnect = MagicMock()
        server.engine_api.open_doc = MagicMock(return_value={"qReturn": {"qHandle": 777}})
        
        # Mock ExportImg to fail with Method not found, return layout fallback
        server.engine_api.export_visualization_to_image = MagicMock(
            return_value={
                "qUrl": "/some/layout/image.png",
                "qWarnings": ["ExportImg not available; using image URL from layout as fallback"],
                "fallback_method": "layout_extraction",
            }
        )

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                params={
                    "name": "engine_export_visualization_to_image",
                    "arguments": {"app_id": TEST_APP_ID, "object_id": "obj-1"},
                }
            )
        )
        payload = json.loads(result.root.content[0].text)

        assert payload["qUrl"] == "/some/layout/image.png"
        assert payload.get("fallback_method") == "layout_extraction"
