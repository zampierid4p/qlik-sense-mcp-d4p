"""Main MCP Server for Qlik Sense APIs."""

import asyncio
import base64
import json
import ssl
import sys
from typing import Any, Dict, List, Optional
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities, Tool
from mcp.types import CallToolResult, TextContent

from .config import (
    QlikSenseConfig,
    DEFAULT_APPS_LIMIT,
    MAX_APPS_LIMIT,
    DEFAULT_FIELD_LIMIT,
    MAX_FIELD_LIMIT,
    DEFAULT_HYPERCUBE_MAX_ROWS,
    DEFAULT_FIELD_FETCH_SIZE,
    MAX_FIELD_FETCH_SIZE,
    DEFAULT_TICKET_TIMEOUT,
    validate_cert_file_paths,
)
from .repository_api import QlikRepositoryAPI
from .engine_api import QlikEngineAPI
from .utils import generate_xrfkey, validate_app_id
from . import __version__

import httpx
import logging
import os
from dotenv import load_dotenv

# Initialize logging configuration early
load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure root logger to stderr (stdout reserved for MCP protocol)
_logging_level = getattr(logging, LOG_LEVEL, logging.INFO)
if not logging.getLogger().handlers:
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(_logging_level)
logger = logging.getLogger(__name__)


def _make_error(message: str, **extra: Any) -> Dict[str, Any]:
    """Create a standardized error response dict."""
    result = {"error": message}
    result.update(extra)
    return result


def _format_init_exception(exc: Exception) -> str:
    """Format initialization exceptions with file path details when available."""
    filename = getattr(exc, "filename", None)
    strerror = getattr(exc, "strerror", None)
    if filename and strerror:
        return f"{strerror}: {filename}"
    if filename:
        return f"{exc} (path: {filename})"
    return str(exc)


class QlikSenseMCPServer:
    """MCP Server for Qlik Sense Enterprise APIs."""

    def __init__(self):
        try:
            self.config = QlikSenseConfig.from_env()
            self.config_valid = self._validate_config()
        except Exception as e:
            self.config = None
            self.config_valid = False

        # Initialize API clients safely
        self.repository_api = None
        self.engine_api = None

        if self.config_valid:
            try:
                self._validate_cert_paths()
                self.repository_api = QlikRepositoryAPI(self.config)
                self.engine_api = QlikEngineAPI(self.config)
            except Exception as e:
                # API clients will be None, tools will return errors
                logging.getLogger(__name__).warning(
                    "Failed to initialize APIs: %s",
                    _format_init_exception(e),
                )

        self.server = Server("qlik-sense-mcp-server")
        self._setup_handlers()

    def _validate_config(self) -> bool:
        """Validate that required configuration is present."""
        if not self.config:
            return False
        return bool(
            self.config.server_url and
            self.config.user_directory and
            self.config.user_id
        )

    def _validate_cert_paths(self) -> None:
        """Validate certificate file paths when provided in configuration."""
        validate_cert_file_paths(
            self.config.client_cert_path,
            self.config.client_key_path,
            self.config.ca_cert_path,
        )

    def _create_httpx_client(self) -> httpx.Client:
        """Create an httpx client configured with Qlik certificates."""
        if self.config.verify_ssl:
            ssl_context = ssl.create_default_context()
            if self.config.ca_cert_path:
                ssl_context.load_verify_locations(self.config.ca_cert_path)
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        cert = None
        if self.config.client_cert_path and self.config.client_key_path:
            cert = (self.config.client_cert_path, self.config.client_key_path)

        return httpx.Client(
            verify=ssl_context if self.config.verify_ssl else False,
            cert=cert,
            timeout=DEFAULT_TICKET_TIMEOUT,
        )

    def _get_qlik_ticket(self) -> Optional[str]:
        """Get Qlik Sense ticket for user authentication."""
        ticket_url = f"{self.config.server_url}:{self.config.proxy_port}/qps/ticket"

        ticket_data = {
            "UserDirectory": self.config.user_directory,
            "UserId": self.config.user_id,
            "Attributes": []
        }

        xrfkey = generate_xrfkey()
        headers = {
            "Content-Type": "application/json",
            "X-Qlik-Xrfkey": xrfkey
        }
        params = {"xrfkey": xrfkey}

        try:
            client = self._create_httpx_client()
            try:
                response = client.post(
                    ticket_url,
                    json=ticket_data,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()

                ticket_response = response.json()
                ticket = ticket_response.get("Ticket")

                if not ticket:
                    raise ValueError("Ticket not found in response")

                return ticket
            finally:
                client.close()

        except Exception as e:
            logger.error(f"Failed to get ticket: {e}")
            return None

    def _get_app_metadata_via_proxy(self, app_id: str, ticket: str) -> Dict[str, Any]:
        """Get application metadata via Qlik Sense Proxy API."""
        server_url = self.config.server_url
        if self.config.http_port:
            server_url = f"{server_url}:{self.config.http_port}"
        metadata_url = f"{server_url}/api/v1/apps/{app_id}/data/metadata?qlikTicket={ticket}"

        xrfkey = generate_xrfkey()
        headers = {"X-Qlik-Xrfkey": xrfkey}
        params = {"xrfkey": xrfkey}

        try:
            client = self._create_httpx_client()
            try:
                response = client.get(
                    metadata_url,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()

                metadata = response.json()
                return self._filter_metadata(metadata)
            finally:
                client.close()

        except Exception as e:
            logger.error(f"Failed to get app metadata: {e}")
            return _make_error(str(e))

    def _build_qlik_download_url(self, image_url: str) -> str:
        """Build absolute URL for image download from Qlik server."""
        if image_url.startswith("http://") or image_url.startswith("https://"):
            return image_url

        base_url = self.config.server_url.rstrip("/")
        if self.config.http_port and f":{self.config.http_port}" not in base_url:
            base_url = f"{base_url}:{self.config.http_port}"

        relative = image_url if image_url.startswith("/") else f"/{image_url}"
        return f"{base_url}{relative}"

    def _download_binary_from_qlik(self, image_url: str) -> Dict[str, Any]:
        """Download binary content from Qlik server using configured certificates."""
        absolute_url = self._build_qlik_download_url(image_url)
        xrfkey = generate_xrfkey()
        headers = {"X-Qlik-Xrfkey": xrfkey}
        params = {"xrfkey": xrfkey}

        client = self._create_httpx_client()
        try:
            response = client.get(absolute_url, headers=headers, params=params)
            response.raise_for_status()
            return {
                "content": response.content,
                "content_type": response.headers.get("content-type", "application/octet-stream"),
                "download_url": absolute_url,
            }
        finally:
            client.close()

    def _capture_visualization_image_headless(self, app_id: str, object_id: str) -> Dict[str, Any]:
        """Capture visualization image through Playwright as best-effort fallback.

        This fallback is optional and only used when no direct image URL is available.
        It lazily imports Playwright so environments without browser dependencies
        can still use the API-first path.
        """
        try:
            import importlib

            sync_api = importlib.import_module("playwright.sync_api")
            sync_playwright = getattr(sync_api, "sync_playwright")
            PlaywrightTimeoutError = getattr(sync_api, "TimeoutError")
        except Exception as exc:
            return _make_error(
                "Headless fallback unavailable: install playwright and browser binaries",
                details=str(exc),
            )

        timeout_seconds = int(os.getenv("HEADLESS_SCREENSHOT_TIMEOUT", "30"))
        timeout_ms = max(timeout_seconds, 5) * 1000
        viewport_width = int(os.getenv("HEADLESS_VIEWPORT_WIDTH", "1920"))
        viewport_height = int(os.getenv("HEADLESS_VIEWPORT_HEIGHT", "1080"))
        executable_path = os.getenv("HEADLESS_BROWSER_EXECUTABLE") or None
        user_directory = self.config.user_directory
        user_id = self.config.user_id
        target_url = f"{self.config.server_url.rstrip('/')}/single/?appid={app_id}&obj={object_id}"

        with sync_playwright() as playwright:
            browser = None
            context = None
            try:
                launch_options: Dict[str, Any] = {
                    "headless": True,
                }
                if executable_path:
                    launch_options["executable_path"] = executable_path

                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    ignore_https_errors=not self.config.verify_ssl,
                    extra_http_headers={
                        "X-Qlik-User": f"UserDirectory={user_directory}; UserId={user_id}"
                    },
                )

                page = context.new_page()
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)

                preferred_selectors = [
                    f"[data-qvid='{object_id}']",
                    f"#{object_id}",
                    "svg",
                    "canvas",
                ]

                image_bytes: Optional[bytes] = None
                for selector in preferred_selectors:
                    try:
                        locator = page.locator(selector).first
                        locator.wait_for(state="visible", timeout=3000)
                        image_bytes = locator.screenshot(type="png")
                        if image_bytes:
                            break
                    except Exception:
                        continue

                if not image_bytes:
                    image_bytes = page.screenshot(type="png", full_page=True)

                return {
                    "format": "png",
                    "content_type": "image/png",
                    "content": image_bytes,
                    "capture_mode": "headless",
                    "source_url": target_url,
                }
            except PlaywrightTimeoutError:
                return _make_error(
                    "Headless fallback timeout while rendering visualization",
                    app_id=app_id,
                    object_id=object_id,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                if context:
                    context.close()
                if browser:
                    browser.close()

    def _capture_visualization_pdf_headless(self, app_id: str, object_id: str) -> Dict[str, Any]:
        """Capture a visualization as PDF through Playwright as best-effort fallback."""
        try:
            import importlib

            sync_api = importlib.import_module("playwright.sync_api")
            sync_playwright = getattr(sync_api, "sync_playwright")
            PlaywrightTimeoutError = getattr(sync_api, "TimeoutError")
        except Exception as exc:
            return _make_error(
                "Headless fallback unavailable: install playwright and browser binaries",
                details=str(exc),
            )

        timeout_seconds = int(os.getenv("HEADLESS_SCREENSHOT_TIMEOUT", "30"))
        timeout_ms = max(timeout_seconds, 5) * 1000
        viewport_width = int(os.getenv("HEADLESS_VIEWPORT_WIDTH", "1920"))
        viewport_height = int(os.getenv("HEADLESS_VIEWPORT_HEIGHT", "1080"))
        executable_path = os.getenv("HEADLESS_BROWSER_EXECUTABLE") or None
        user_directory = self.config.user_directory
        user_id = self.config.user_id
        target_url = f"{self.config.server_url.rstrip('/')}/single/?appid={app_id}&obj={object_id}"

        with sync_playwright() as playwright:
            browser = None
            context = None
            try:
                launch_options: Dict[str, Any] = {
                    "headless": True,
                }
                if executable_path:
                    launch_options["executable_path"] = executable_path

                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    ignore_https_errors=not self.config.verify_ssl,
                    extra_http_headers={
                        "X-Qlik-User": f"UserDirectory={user_directory}; UserId={user_id}"
                    },
                )

                page = context.new_page()
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)

                preferred_selectors = [
                    f"[data-qvid='{object_id}']",
                    f"#{object_id}",
                    "svg",
                    "canvas",
                ]
                for selector in preferred_selectors:
                    try:
                        locator = page.locator(selector).first
                        locator.wait_for(state="visible", timeout=3000)
                        break
                    except Exception:
                        continue

                pdf_bytes = page.pdf(print_background=True)
                return {
                    "format": "pdf",
                    "content_type": "application/pdf",
                    "content": pdf_bytes,
                    "capture_mode": "headless",
                    "source_url": target_url,
                }
            except PlaywrightTimeoutError:
                return _make_error(
                    "Headless fallback timeout while rendering visualization",
                    app_id=app_id,
                    object_id=object_id,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                if context:
                    context.close()
                if browser:
                    browser.close()

    def _filter_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Filter metadata to remove system fields and hidden items."""
        # Fields to remove from output
        fields_to_remove = {
            'is_system', 'is_hidden', 'is_semantic', 'distinct_only',
            'is_locked', 'always_one_selected', 'is_numeric', 'hash',
            'tags', 'has_section_access', 'tables_profiling_data',
            'is_direct_query_mode', 'usage', 'reload_meta', 'static_byte_size', 'byte_size', 'no_of_key_fields'
        }

        # Qlik Sense reserved fields to remove
        qlik_reserved_fields = {'$Field', '$Table', '$Rows', '$Fields', '$FieldNo', '$Info'}

        def filter_object(obj):
            """Recursively filter object."""
            if isinstance(obj, dict):
                filtered = {}
                for key, value in obj.items():
                    if key in fields_to_remove:
                        continue
                    if isinstance(value, dict):
                        if value.get('is_system') or value.get('is_hidden'):
                            continue
                        if key == 'cardinal':
                            filtered['unique_count'] = value
                            continue
                    filtered[key] = filter_object(value)
                return filtered
            elif isinstance(obj, list):
                if obj and isinstance(obj[0], dict) and 'name' in obj[0]:
                    return [filter_object(item) for item in obj if item.get('name') not in qlik_reserved_fields]
                else:
                    return [filter_object(item) for item in obj]
            else:
                return obj

        filtered = filter_object(metadata)
        result = {}

        if 'fields' in filtered:
            result['fields'] = filtered['fields']
        if 'tables' in filtered:
            result['tables'] = filtered['tables']

        return result

    def _resolve_app_id(self, name_or_id: str) -> str:
        """Resolve an application identifier that can be either GUID or app name."""
        if not name_or_id or not str(name_or_id).strip():
            raise ValueError("Application GUID or name must be provided")

        candidate = str(name_or_id).strip()
        if validate_app_id(candidate):
            return candidate

        direct_lookup = self.repository_api.get_app_by_id(candidate)
        if isinstance(direct_lookup, dict) and direct_lookup.get("id"):
            return str(direct_lookup["id"])

        apps_payload = self.repository_api.get_comprehensive_apps(
            limit=MAX_APPS_LIMIT,
            offset=0,
            name=candidate,
            stream=None,
            published=None,
        )
        apps = apps_payload.get("apps", []) if isinstance(apps_payload, dict) else []
        if not apps:
            raise ValueError(f"App not found: {candidate}")

        lowered = candidate.lower()
        exact_match = next((app for app in apps if app.get("name", "").lower() == lowered), None)
        selected = exact_match or apps[0]
        app_id = selected.get("guid", "")
        if not app_id:
            raise ValueError(f"App not found: {candidate}")

        return str(app_id)

    def _setup_handlers(self):
        """Setup MCP server handlers."""

        @self.server.list_tools()
        async def handle_list_tools():
            """
            List all available MCP tools for Qlik Sense operations.

            Returns tool definitions with schemas for Repository API and Engine API operations
            including applications, analytics tools, and data export.
            """
            tools_list = [
                Tool(
                    name="get_apps",
                    description="Get list of Qlik Sense applications with essential fields and filters (name, stream, published) and pagination. Use stream='My Work' to list personal unpublished apps.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": f"Maximum number of apps to return (default: {DEFAULT_APPS_LIMIT}, max: {MAX_APPS_LIMIT})",
                                "default": DEFAULT_APPS_LIMIT
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of apps to skip for pagination (default: 0)",
                                "default": 0
                            },
                            "name": {
                                "type": "string",
                                "description": "Wildcard case-insensitive search in application name"
                            },
                            "stream": {
                                "type": "string",
                                "description": "Wildcard case-insensitive search in stream name. Use 'My Work' to list personal unpublished apps."
                            },
                            "published": {
                                "type": "boolean",
                                "description": "Filter by published status. Default: true. Ignored when stream='My Work'.",
                                "default": True
                            }
                        }
                    }
                ),
                Tool(
                    name="get_app_details",
                    description="Get detailed application info by guid or name (case-insensitive). Returns metainfo, fields and tables.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID (preferred if known)"},
                            "name": {"type": "string", "description": "Case-insensitive fuzzy search by app name"},
                            "appId": {"type": "string", "description": "Compatibility alias for app_id used by some clients"},
                            "appName": {"type": "string", "description": "Compatibility alias for name used by some clients"}
                        }
                    }
                ),

                Tool(name="get_app_script", description="Get load script from app", inputSchema={"type": "object", "properties": {"app_id": {"type": "string", "description": "Application GUID or application name"}}, "required": ["app_id"]}),
                Tool(name="get_app_field_statistics", description="Get comprehensive statistics for a field", inputSchema={"type": "object", "properties": {"app_id": {"type": "string", "description": "Application GUID or application name"}, "field_name": {"type": "string", "description": "Field name"}}, "required": ["app_id", "field_name"]}),
                Tool(name="engine_create_hypercube", description="Create hypercube for data analysis with custom sorting options. IMPORTANT: To get top-N records, use qSortByExpression: 1 in dimension sorting with qExpression containing the measure formula (e.g., 'Count(field)' for ascending, '-Count(field)' for descending). Measure sorting is ignored by Qlik Engine.", inputSchema={
                    "type": "object",
                    "properties": {
                        "app_id": {"type": "string", "description": "Application GUID or application name"},
                        "dimensions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string", "description": "Field name for dimension"},
                                    "label": {"type": "string", "description": "Optional label for dimension"},
                                    "sort_by": {
                                        "type": "object",
                                        "properties": {
                                            "qSortByNumeric": {"type": "integer", "description": "Sort by numeric value (-1 desc, 0 none, 1 asc)", "default": 0},
                                            "qSortByAscii": {"type": "integer", "description": "Sort by ASCII value (-1 desc, 0 none, 1 asc)", "default": 1},
                                            "qSortByExpression": {"type": "integer", "description": "Use expression for sorting (0/1). For top-N results, set to 1 and use qExpression with measure formula", "default": 0},
                                            "qExpression": {"type": "string", "description": "Expression for custom sorting. For top-N: 'Count(field)' for ascending, '-Count(field)' for descending", "default": ""}
                                        },
                                        "additionalProperties": False
                                    }
                                },
                                "additionalProperties": False
                            },
                            "description": "List of dimension definitions with optional sorting"
                        },
                        "measures": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "expression": {"type": "string", "description": "Measure expression"},
                                    "label": {"type": "string", "description": "Optional label for measure"},
                                    "sort_by": {
                                        "type": "object",
                                        "properties": {
                                            "qSortByNumeric": {"type": "integer", "description": "Sort by numeric value (-1 desc, 0 none, 1 asc). NOTE: Measure sorting is ignored by Qlik Engine - use dimension sorting with qSortByExpression for top-N results", "default": -1}
                                        },
                                        "additionalProperties": False
                                    }
                                },
                                "additionalProperties": False
                            },
                            "description": "List of measure definitions with optional sorting"
                        },
                        "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": DEFAULT_HYPERCUBE_MAX_ROWS}
                    },
                    "required": ["app_id"]
                })
                ,
                Tool(
                    name="get_app_field",
                    description="Return values of a single field from app with pagination and wildcard search (supports * and %).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "field_name": {"type": "string", "description": "Field name"},
                            "limit": {"type": "integer", "description": f"Max values to return (default: {DEFAULT_FIELD_LIMIT}, max: {MAX_FIELD_LIMIT})", "default": DEFAULT_FIELD_LIMIT},
                            "offset": {"type": "integer", "description": "Offset for pagination (default: 0)", "default": 0},
                            "search_string": {"type": "string", "description": "Wildcard text search mask (* and % supported), case-insensitive by default"},
                            "search_number": {"type": "string", "description": "Wildcard numeric search mask (* and % supported)"},
                            "case_sensitive": {"type": "boolean", "description": "Case sensitive matching for search_string", "default": False}
                        },
                        "required": ["app_id", "field_name"],
                    }
                ),
                Tool(
                    name="get_app_variables",
                    description="Return variables split by source (script/ui) with pagination and wildcard search.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "limit": {"type": "integer", "description": f"Max variables to return (default: {DEFAULT_FIELD_LIMIT}, max: {MAX_FIELD_LIMIT})", "default": DEFAULT_FIELD_LIMIT},
                            "offset": {"type": "integer", "description": "Offset for pagination (default: 0)", "default": 0},
                            "created_in_script": {"type": "string", "description": "Return only variables created in script (true/false). If omitted, return both"},
                            "search_string": {"type": "string", "description": "Wildcard search by variable name or text value (* and % supported), case-insensitive by default"},
                            "search_number": {"type": "string", "description": "Wildcard search among numeric variable values (* and % supported)"},
                            "case_sensitive": {"type": "boolean", "description": "Case sensitive matching for search_string", "default": False}
                        },
                        "required": ["app_id"],
                    }
                ),
                Tool(
                    name="get_app_sheets",
                    description="Get list of sheets from application with title and description.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="get_app_sheet_objects",
                    description="Get list of objects from specific sheet with object ID, type and description.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "sheet_id": {"type": "string", "description": "Sheet GUID"}
                        },
                        "required": ["app_id", "sheet_id"]
                    }
                ),
                Tool(
                    name="get_app_object",
                    description="Get specific object layout by calling GetObject and GetLayout sequentially via WebSocket.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Object ID to retrieve"}
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="get_visualization_image",
                    description="Return visualization image as base64 by resolving image URL via Engine API layout/snapshot and downloading it from Qlik Sense for Windows, with optional headless fallback.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"},
                            "format": {
                                "type": "string",
                                "description": "Preferred output format hint (auto/png/svg/jpeg). The tool returns original content format from Qlik.",
                                "default": "auto"
                            },
                            "headless_fallback": {
                                "type": "boolean",
                                "description": "If true, try browser screenshot fallback when Engine API does not provide an image URL.",
                                "default": False
                            }
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="get_app_reload_chain",
                    description="Get reload tasks and recent execution history for an app.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="get_app_objects_detailed",
                    description="Get repository objects for an app, optionally filtered by object type.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_type": {"type": "string", "description": "Optional repository object type filter"}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="engine_get_field_info",
                    description="Get field description and sample values from the Engine API.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "field_name": {"type": "string", "description": "Field name"}
                        },
                        "required": ["app_id", "field_name"]
                    }
                ),
                Tool(
                    name="engine_extract_data",
                    description="Create a hypercube and return extracted data rows.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "dimensions": {"type": "array", "items": {"type": "object"}, "description": "Dimension definitions", "default": []},
                            "measures": {"type": "array", "items": {"type": "object"}, "description": "Measure definitions", "default": []},
                            "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": DEFAULT_HYPERCUBE_MAX_ROWS}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="engine_get_visualization_data",
                    description="Get data for an existing visualization object through the Engine API.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"}
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="engine_search_and_analyze",
                    description="Search app objects and fields for one or more search terms.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "search_terms": {"type": "array", "items": {"type": "string"}, "description": "Search terms to analyze"}
                        },
                        "required": ["app_id", "search_terms"]
                    }
                ),
                Tool(
                    name="engine_get_master_items",
                    description="Get master dimensions, measures and variables from an app.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="engine_calculate_expression",
                    description="Calculate an expression in app context, optionally grouped by dimensions.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "expression": {"type": "string", "description": "Qlik expression to evaluate"},
                            "dimensions": {"type": "array", "items": {"type": "string"}, "description": "Optional dimensions", "default": []}
                        },
                        "required": ["app_id", "expression"]
                    }
                ),
                Tool(
                    name="engine_get_associations",
                    description="Get field associations and data model information for an app.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="engine_smart_search",
                    description="Get smart search suggestions for one or more terms.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "search_terms": {"type": "array", "items": {"type": "string"}, "description": "Search terms"}
                        },
                        "required": ["app_id", "search_terms"]
                    }
                ),
                Tool(
                    name="engine_create_pivot_analysis",
                    description="Create a pivot analysis from dimensions and measures.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "dimensions": {"type": "array", "items": {"type": "object"}, "description": "Dimension definitions", "default": []},
                            "measures": {"type": "array", "items": {"type": "object"}, "description": "Measure definitions", "default": []},
                            "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": DEFAULT_HYPERCUBE_MAX_ROWS}
                        },
                        "required": ["app_id"]
                    }
                ),
                Tool(
                    name="engine_create_simple_table",
                    description="Create a simple table from dimensions and optional measures.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "dimensions": {"type": "array", "items": {"type": "object"}, "description": "Dimension definitions"},
                            "measures": {"type": "array", "items": {"type": "object"}, "description": "Measure definitions", "default": []},
                            "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": DEFAULT_HYPERCUBE_MAX_ROWS}
                        },
                        "required": ["app_id", "dimensions"]
                    }
                ),
                Tool(
                    name="engine_get_chart_data",
                    description="Build chart data for a given chart type.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "chart_type": {"type": "string", "description": "Chart type to generate"},
                            "dimensions": {"type": "array", "items": {"type": "object"}, "description": "Dimension definitions", "default": []},
                            "measures": {"type": "array", "items": {"type": "object"}, "description": "Measure definitions", "default": []},
                            "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": DEFAULT_HYPERCUBE_MAX_ROWS}
                        },
                        "required": ["app_id", "chart_type"]
                    }
                ),
                Tool(
                    name="engine_export_visualization_to_csv",
                    description="Export visualization data to CSV via GenericObject ExportData and return download URL.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"},
                            "q_path": {"type": "string", "description": "Path to object definition for CSV export (default: /qHyperCubeDef)", "default": "/qHyperCubeDef"},
                            "q_export_state": {"type": "string", "description": "Export state: A (all) or P (possible)", "default": "A"},
                            "q_serve_once": {"type": "boolean", "description": "Serve export URL only once", "default": False}
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="engine_export_visualization_to_xlsx",
                    description="Export visualization data to XLSX (OOXML) via GenericObject ExportData.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"},
                            "q_export_state": {"type": "string", "description": "Export state: A (all) or P (possible)", "default": "A"},
                            "q_serve_once": {"type": "boolean", "description": "Serve export URL only once", "default": False}
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="engine_export_visualization_to_pdf",
                    description="Export visualization to PDF via GenericObject ExportPdf.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"},
                            "headless_fallback": {"type": "boolean", "description": "If true, use a browser-rendered base64 PDF when native Engine export does not provide qUrl.", "default": False}
                        },
                        "required": ["app_id", "object_id"]
                    }
                ),
                Tool(
                    name="engine_export_visualization_to_image",
                    description="Export visualization to image via GenericObject ExportImg.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "app_id": {"type": "string", "description": "Application GUID or application name"},
                            "object_id": {"type": "string", "description": "Visualization object ID"},
                            "headless_fallback": {"type": "boolean", "description": "If true, use a browser-rendered base64 image when native Engine export does not provide qUrl.", "default": False}
                        },
                        "required": ["app_id", "object_id"]
                    }
                )
                ]
            return tools_list

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]):
            # Check configuration before processing any tool calls
            if not self.config_valid:
                error_msg = _make_error(
                    "Qlik Sense configuration missing",
                    message="Please set the following environment variables:",
                    required=[
                        "QLIK_SERVER_URL - Qlik Sense server URL",
                        "QLIK_USER_DIRECTORY - User directory",
                        "QLIK_USER_ID - User ID",
                        "QLIK_CLIENT_CERT_PATH - Path to client certificate",
                        "QLIK_CLIENT_KEY_PATH - Path to client key",
                        "QLIK_CA_CERT_PATH - Path to CA certificate"
                    ],
                    example="uvx --with-env QLIK_SERVER_URL=https://qlik.company.com qlik-sense-mcp-server"
                )
                return [TextContent(type="text", text=json.dumps(error_msg, indent=2))]
            """
            Handle MCP tool calls by routing to appropriate API handlers.

            Args:
                name: Tool name to execute
                arguments: Tool-specific parameters

            Returns:
                TextContent with JSON response from Qlik Sense APIs
            """
            try:
                if name == "get_apps":
                    limit = arguments.get("limit", DEFAULT_APPS_LIMIT)
                    offset = arguments.get("offset", 0)
                    name_filter = arguments.get("name")
                    stream_filter = arguments.get("stream")
                    published_arg = arguments.get("published", True)

                    if limit is None or limit < 1:
                        limit = DEFAULT_APPS_LIMIT
                    if limit > MAX_APPS_LIMIT:
                        limit = MAX_APPS_LIMIT

                    def _to_bool(value: Any, default: bool = True) -> bool:
                        if isinstance(value, bool):
                            return value
                        if isinstance(value, int):
                            return value != 0
                        if isinstance(value, str):
                            v = value.strip().lower()
                            if v in ("true", "1", "yes", "y"): return True
                            if v in ("false", "0", "no", "n"): return False
                        return default

                    published_bool = _to_bool(published_arg, True)

                    apps_payload = await asyncio.to_thread(
                        self.repository_api.get_comprehensive_apps,
                        limit,
                        offset,
                        name_filter,
                        stream_filter,
                        published_bool,
                    )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(apps_payload, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_app_details":
                    # Compatibility aliases for clients that rename snake_case fields.
                    req_app_id = arguments.get("app_id") or arguments.get("appId") or arguments.get("id")
                    req_name = arguments.get("name") or arguments.get("appName")

                    def _get_app_details():
                        """Get application details with metadata, fields and tables."""
                        try:
                            if req_app_id:
                                app_id = self._resolve_app_id(req_app_id)
                            elif req_name:
                                app_id = self._resolve_app_id(req_name)
                            else:
                                return _make_error("Either app_id or name must be provided")

                            app_meta = self.repository_api.get_app_by_id(app_id)
                            if not isinstance(app_meta, dict) or not app_meta.get("id"):
                                return _make_error("App not found by provided app_id")

                            resolved = {
                                "app_id": app_meta.get("id"),
                                "name": app_meta.get("name", ""),
                                "description": app_meta.get("description") or "",
                                "stream": (app_meta.get("stream", {}) or {}).get("name", "") if app_meta.get("published") else "",
                                "modified_dttm": app_meta.get("modifiedDate", "") or "",
                                "reload_dttm": app_meta.get("lastReloadTime", "") or "",
                            }

                            metadata = None
                            proxy_error = None

                            ticket = self._get_qlik_ticket()
                            if ticket:
                                metadata = self._get_app_metadata_via_proxy(app_id, ticket)
                                if "error" in metadata:
                                    proxy_error = metadata["error"]
                                    logger.warning(
                                        "Proxy metadata lookup failed for app %s, falling back to Engine API: %s",
                                        app_id,
                                        proxy_error,
                                    )
                                    metadata = None
                            else:
                                proxy_error = "Failed to obtain Qlik ticket"
                                logger.warning(
                                    "Qlik ticket unavailable for app %s, falling back to Engine API",
                                    app_id,
                                )

                            if metadata is None:
                                if not self.engine_api:
                                    return _make_error(proxy_error or "Failed to initialize Engine API")

                                metadata = self.engine_api.get_detailed_app_metadata(app_id)
                                if "error" in metadata:
                                    return metadata

                            result = {
                                "metainfo": {
                                    "app_id": app_id,
                                    "name": resolved.get("name", ""),
                                    "description": resolved.get("description", ""),
                                    "stream": resolved.get("stream", ""),
                                    "modified_dttm": resolved.get("modified_dttm", ""),
                                    "reload_dttm": resolved.get("reload_dttm", "")
                                },
                                "fields": metadata.get("fields", []),
                                "tables": metadata.get("tables", [])
                            }

                            return result

                        except Exception as e:
                            return _make_error(str(e))

                    details = await asyncio.to_thread(_get_app_details)
                    return [
                        TextContent(type="text", text=json.dumps(details, indent=2, ensure_ascii=False))
                    ]

                elif name == "get_app_script":
                    app_id = self._resolve_app_id(arguments["app_id"])

                    def _get_script():
                        app_handle = -1
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=True)
                            if "qReturn" not in app_result:
                                raise Exception(f"Failed to open app: invalid response {app_result}")
                            app_handle = app_result["qReturn"].get("qHandle", -1)
                            if app_handle == -1:
                                raise Exception(f"Failed to get app handle: {app_result}")
                            script = self.engine_api.get_script(app_handle)
                            return {
                                "qScript": script,
                                "app_id": app_id,
                                "app_handle": app_handle,
                                "script_length": len(script) if script else 0
                            }
                        except Exception as e:
                            error_msg = str(e)
                            if "already open" in error_msg.lower():
                                error_msg = f"App {app_id} is already open in another session. Try again later or use a different session."
                            elif "failed to open app" in error_msg.lower():
                                error_msg = f"Could not open app {app_id}. Check if app exists and you have access."
                            return _make_error(error_msg, app_id=app_id, app_handle=app_handle)
                        finally:
                            if app_handle != -1:
                                try:
                                    self.engine_api.close_doc(app_handle)
                                except Exception:
                                    pass
                            self.engine_api.disconnect()

                    script = await asyncio.to_thread(_get_script)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(script, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_app_field_statistics":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    field_name = arguments["field_name"]

                    def _get_field_statistics():
                        app_handle = -1
                        debug_info = []
                        try:
                            debug_info.append(f"Starting field statistics for app_id={app_id}, field_name={field_name}")
                            self.engine_api.connect()
                            debug_info.append("Connected to engine")
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=False)
                            debug_info.append(f"App open result: {app_result}")
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            debug_info.append(f"App handle: {app_handle}")
                            if app_handle != -1:
                                result = self.engine_api.get_field_statistics(app_handle, field_name)
                                debug_info.append("Field statistics method completed")
                                if isinstance(result, dict) and "debug_log" not in result:
                                    result["server_debug"] = debug_info
                                return result
                            else:
                                raise Exception(f"Failed to open app: {app_result}")
                        except Exception as e:
                            import traceback
                            debug_info.append(f"Exception in server handler: {e}")
                            debug_info.append(f"Traceback: {traceback.format_exc()}")
                            return _make_error(
                                str(e),
                                server_debug=debug_info,
                                traceback=traceback.format_exc()
                            )
                        finally:
                            debug_info.append("Disconnecting from engine")
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_field_statistics)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_create_hypercube":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    dimensions = arguments.get("dimensions", [])
                    measures = arguments.get("measures", [])
                    max_rows = arguments.get("max_rows", DEFAULT_HYPERCUBE_MAX_ROWS)

                    def _create_hypercube():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                return self.engine_api.create_hypercube(app_handle, dimensions, measures, max_rows)
                            else:
                                raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_create_hypercube)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_app_reload_chain":
                    app_id = self._resolve_app_id(arguments["app_id"])

                    def _get_reload_chain():
                        tasks = self.repository_api.get_reload_tasks_for_app(app_id)
                        chain_info = {
                            "app_id": app_id,
                            "reload_tasks": [],
                            "execution_history": []
                        }
                        for task in tasks:
                            task_id = task.get("id")
                            if task_id:
                                executions = self.repository_api.get_task_executions(task_id, 10)
                                chain_info["reload_tasks"].append(task)
                                chain_info["execution_history"].extend(executions)
                        return chain_info

                    chain = await asyncio.to_thread(_get_reload_chain)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(chain, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_app_objects_detailed":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_type = arguments.get("object_type")
                    objects = await asyncio.to_thread(self.repository_api.get_app_objects, app_id, object_type)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(objects, indent=2, ensure_ascii=False)
                        )
                    ]
                elif name == "get_app_field":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    field_name = arguments["field_name"]
                    limit = arguments.get("limit", DEFAULT_FIELD_LIMIT)
                    offset = arguments.get("offset", 0)
                    search_string = arguments.get("search_string")
                    search_number = arguments.get("search_number")
                    case_sensitive = arguments.get("case_sensitive", False)

                    if limit is None or limit < 1:
                        limit = DEFAULT_FIELD_LIMIT
                    if limit > MAX_FIELD_LIMIT:
                        limit = MAX_FIELD_LIMIT
                    if offset is None or offset < 0:
                        offset = 0

                    def _wildcard_to_regex(pattern: str, case_sensitive_flag: bool) -> Any:
                        import re
                        escaped = re.escape(pattern).replace("\\*", ".*").replace("%", ".*")
                        regex = f"^{escaped}$"
                        return re.compile(regex, 0 if case_sensitive_flag else re.IGNORECASE)

                    def _get_values():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle == -1:
                                return _make_error("Failed to open app")

                            fetch_size = max(limit + offset, DEFAULT_FIELD_FETCH_SIZE)
                            if fetch_size > MAX_FIELD_FETCH_SIZE:
                                fetch_size = MAX_FIELD_FETCH_SIZE
                            field_data = self.engine_api.get_field_values(app_handle, field_name, fetch_size, include_frequency=False)
                            values = [v.get("value", "") for v in field_data.get("values", [])]

                            if search_string:
                                rx = _wildcard_to_regex(search_string, case_sensitive)
                                values = [val for val in values if isinstance(val, str) and rx.match(val)]

                            if search_number:
                                rxn = _wildcard_to_regex(search_number, case_sensitive)
                                filtered = []
                                for idx, vobj in enumerate(field_data.get("values", [])):
                                    cell_text = vobj.get("value", "")
                                    qnum = vobj.get("numeric_value", None)
                                    if qnum is not None:
                                        if rxn.match(str(qnum)) or rxn.match(str(cell_text)):
                                            filtered.append(cell_text)
                                values = filtered

                            sliced = values[offset:offset + limit]
                            return {"field_values": sliced}
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_values)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "get_app_variables":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    limit = arguments.get("limit", DEFAULT_FIELD_LIMIT)
                    offset = arguments.get("offset", 0)
                    created_in_script_arg = arguments.get("created_in_script", None)
                    search_string = arguments.get("search_string")
                    search_number = arguments.get("search_number")
                    case_sensitive = arguments.get("case_sensitive", False)

                    if limit is None or limit < 1:
                        limit = DEFAULT_FIELD_LIMIT
                    if limit > MAX_FIELD_LIMIT:
                        limit = MAX_FIELD_LIMIT
                    if offset is None or offset < 0:
                        offset = 0

                    def _to_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
                        if value is None:
                            return default
                        if isinstance(value, bool):
                            return value
                        if isinstance(value, int):
                            return value != 0
                        if isinstance(value, str):
                            v = value.strip().lower()
                            if v in ("true", "1", "yes", "y"): return True
                            if v in ("false", "0", "no", "n"): return False
                        return default

                    created_in_script = _to_bool(created_in_script_arg, None)

                    def _wildcard_to_regex(pattern: str, case_sensitive_flag: bool):
                        import re
                        escaped = re.escape(pattern).replace("\\*", ".*").replace("%", ".*")
                        regex = f"^{escaped}$"
                        return re.compile(regex, 0 if case_sensitive_flag else re.IGNORECASE)

                    def _get_variables():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle == -1:
                                return _make_error("Failed to open app")

                            var_list = self.engine_api._get_user_variables(app_handle) or []
                            prepared = []
                            for v in var_list:
                                var_name = v.get("name", "")
                                text_val = v.get("text_value", "")
                                is_script = v.get("is_script_created", False)
                                prepared.append({
                                    "name": var_name,
                                    "text_value": text_val if text_val is not None else "",
                                    "is_script": is_script
                                })

                            if created_in_script is True:
                                prepared = [x for x in prepared if x["is_script"]]
                            elif created_in_script is False:
                                prepared = [x for x in prepared if not x["is_script"]]
                            else:
                                # By default show only UI-created variables
                                prepared = [x for x in prepared if not x["is_script"]]

                            if search_string:
                                rx = _wildcard_to_regex(search_string, case_sensitive)
                                prepared = [x for x in prepared if rx.match(x["name"]) or rx.match(x.get("text_value", ""))]

                            from_script = [x for x in prepared if x["is_script"]]
                            from_ui = [x for x in prepared if not x["is_script"]]

                            def _slice_and_map(items):
                                sliced = items[offset:offset + limit]
                                result_map = {}
                                for it in sliced:
                                    val = it.get("text_value", "")
                                    result_map[it["name"]] = val
                                return result_map

                            res_script = _slice_and_map(from_script)
                            res_ui = _slice_and_map(from_ui)

                            return {
                                "variables_from_script": res_script if res_script else "",
                                "variables_from_ui": res_ui if res_ui else ""
                            }
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_variables)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "get_app_sheets":
                    app_id = self._resolve_app_id(arguments["app_id"])

                    def _get_app_sheets():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=True)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle == -1:
                                return _make_error("Failed to open app")

                            sheets = self.engine_api.get_sheets(app_handle)
                            sheets_list = []
                            for sheet in sheets:
                                sheet_info = sheet.get("qMeta", {})
                                sheets_list.append({
                                    "sheet_id": sheet.get("qInfo", {}).get("qId", ""),
                                    "title": sheet_info.get("title", ""),
                                    "description": sheet_info.get("description", "")
                                })

                            return {
                                "app_id": app_id,
                                "total_sheets": len(sheets_list),
                                "sheets": sheets_list
                            }
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_app_sheets)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "get_app_sheet_objects":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    sheet_id = arguments["sheet_id"]

                    def _get_sheet_objects():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc_safe(app_id, no_data=True)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle == -1:
                                return _make_error("Failed to open app")

                            objects = self.engine_api._get_sheet_objects_detailed(app_handle, sheet_id) or []

                            # Format objects: object id, object type, object description
                            formatted_objects = []
                            for obj in objects:
                                if isinstance(obj, dict):
                                    obj_info = {
                                        "object_id": obj.get("object_id", ""),
                                        "object_type": obj.get("object_type", ""),
                                        "object_description": obj.get("object_title", "")
                                    }
                                    formatted_objects.append(obj_info)

                            return {
                                "app_id": app_id,
                                "sheet_id": sheet_id,
                                "total_objects": len(formatted_objects),
                                "objects": formatted_objects
                            }

                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, sheet_id=sheet_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_sheet_objects)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "engine_get_field_info":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    field_name = arguments["field_name"]

                    def _get_field_info():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                field_desc = self.engine_api.get_field_description(app_handle, field_name)
                                field_values = self.engine_api.get_field_values(app_handle, field_name, 50)
                                return {
                                    "field_description": field_desc,
                                    "sample_values": field_values
                                }
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    field_info = await asyncio.to_thread(_get_field_info)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(field_info, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_extract_data":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    dimensions = arguments.get("dimensions", [])
                    measures = arguments.get("measures", [])
                    max_rows = arguments.get("max_rows", DEFAULT_HYPERCUBE_MAX_ROWS)

                    def _extract_data():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                cube_result = self.engine_api.create_hypercube(app_handle, dimensions, measures, max_rows)
                                cube_handle = cube_result.get("qReturn", {}).get("qHandle", -1)
                                if cube_handle != -1:
                                    data = self.engine_api.get_hypercube_data(cube_handle, 0, max_rows)
                                    return {
                                        "dimensions": dimensions,
                                        "measures": measures,
                                        "data": data
                                    }
                                else:
                                    raise Exception("Failed to create hypercube")
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    data = await asyncio.to_thread(_extract_data)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(data, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_get_visualization_data":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]

                    def _get_visualization_data():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                return self.engine_api.get_visualization_data(app_handle, object_id)
                            else:
                                raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_visualization_data)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_search_and_analyze":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    search_terms = arguments["search_terms"]

                    def _search_analyze():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                search_results = self.engine_api.search_objects(app_handle, search_terms)
                                fields = self.engine_api.get_fields(app_handle)
                                matching_fields = []
                                for field in fields:
                                    field_name = field.get("qName", "").lower()
                                    for term in search_terms:
                                        if term.lower() in field_name:
                                            matching_fields.append(field)
                                            break
                                return {
                                    "search_terms": search_terms,
                                    "object_matches": search_results,
                                    "field_matches": matching_fields
                                }
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    results = await asyncio.to_thread(_search_analyze)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(results, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_get_master_items":
                    app_id = self._resolve_app_id(arguments["app_id"])

                    def _get_master_items():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                dims = self.engine_api.get_dimensions(app_handle)
                                meas = self.engine_api.get_measures(app_handle)
                                variables = self.engine_api.get_variables(app_handle)

                                return {
                                    "master_dimensions": dims,
                                    "master_measures": meas,
                                    "variables": variables
                                }
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    master_items = await asyncio.to_thread(_get_master_items)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(master_items, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_calculate_expression":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    expression = arguments["expression"]
                    dimensions = arguments.get("dimensions", [])

                    def _calculate_expression():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                return self.engine_api.calculate_expression(app_handle, expression, dimensions)
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_calculate_expression)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_get_associations":
                    app_id = self._resolve_app_id(arguments["app_id"])

                    def _get_associations():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                associations = self.engine_api.get_associations(app_handle)
                                data_model = self.engine_api.get_data_model(app_handle)

                                return {
                                    "associations": associations,
                                    "data_model": data_model
                                }
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    associations = await asyncio.to_thread(_get_associations)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(associations, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_smart_search":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    search_terms = arguments["search_terms"]

                    def _smart_search():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                suggestions = self.engine_api.search_suggest(app_handle, search_terms)
                                return {
                                    "search_terms": search_terms,
                                    "suggestions": suggestions
                                }
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    suggestions = await asyncio.to_thread(_smart_search)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(suggestions, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_create_pivot_analysis":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    dimensions = arguments.get("dimensions", [])
                    measures = arguments.get("measures", [])
                    max_rows = arguments.get("max_rows", DEFAULT_HYPERCUBE_MAX_ROWS)

                    def _create_pivot():
                        self.engine_api.connect(app_id)
                        try:
                            app_result = self.engine_api.open_doc(app_id)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                pivot_result = self.engine_api.get_pivot_table_data(app_handle, dimensions, measures, max_rows)
                                pivot_handle = pivot_result.get("qReturn", {}).get("qHandle", -1)

                                if pivot_handle != -1:
                                    layout = self.engine_api.send_request("GetLayout", handle=pivot_handle)
                                    return {
                                        "dimensions": dimensions,
                                        "measures": measures,
                                        "pivot_data": layout
                                    }
                                else:
                                    raise Exception("Failed to create pivot table")
                            else:
                                raise Exception("Failed to open app")
                        finally:
                            self.engine_api.disconnect()

                    pivot_data = await asyncio.to_thread(_create_pivot)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(pivot_data, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_create_simple_table":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    dimensions = arguments["dimensions"]
                    measures = arguments.get("measures", [])
                    max_rows = arguments.get("max_rows", DEFAULT_HYPERCUBE_MAX_ROWS)

                    def _create_simple_table():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                return self.engine_api.create_simple_table(app_handle, dimensions, measures, max_rows)
                            else:
                                raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_create_simple_table)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_get_chart_data":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    chart_type = arguments["chart_type"]
                    dimensions = arguments.get("dimensions", [])
                    measures = arguments.get("measures", [])
                    max_rows = arguments.get("max_rows", DEFAULT_HYPERCUBE_MAX_ROWS)

                    def _get_chart_data():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                return self.engine_api.get_chart_data(app_handle, chart_type, dimensions, measures, max_rows)
                            else:
                                raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e))
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_chart_data)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "engine_export_visualization_to_csv":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]
                    q_path = arguments.get("q_path", "/qHyperCubeDef")
                    q_export_state = str(arguments.get("q_export_state", "A"))
                    q_serve_once = bool(arguments.get("q_serve_once", False))

                    def _export_visualization_csv():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                result = self.engine_api.export_visualization_to_csv(
                                    app_handle,
                                    object_id,
                                    q_path=q_path,
                                    q_export_state=q_export_state,
                                    q_serve_once=q_serve_once,
                                )
                                return {
                                    "app_id": app_id,
                                    "object_id": object_id,
                                    "format": "csv",
                                    **(result if isinstance(result, dict) else {"result": result}),
                                }
                            raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_export_visualization_csv)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "engine_export_visualization_to_xlsx":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]
                    q_export_state = str(arguments.get("q_export_state", "A"))
                    q_serve_once = bool(arguments.get("q_serve_once", False))

                    def _export_visualization_xlsx():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                result = self.engine_api.export_visualization_to_xlsx(
                                    app_handle,
                                    object_id,
                                    q_export_state=q_export_state,
                                    q_serve_once=q_serve_once,
                                )
                                return {
                                    "app_id": app_id,
                                    "object_id": object_id,
                                    "format": "xlsx",
                                    **(result if isinstance(result, dict) else {"result": result}),
                                }
                            raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_export_visualization_xlsx)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "engine_export_visualization_to_pdf":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]
                    headless_fallback = bool(arguments.get("headless_fallback", False))

                    def _export_visualization_pdf():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                result = self.engine_api.export_visualization_to_pdf(app_handle, object_id)
                                if (
                                    isinstance(result, dict)
                                    and "qUrl" not in result
                                    and "error" in result
                                    and headless_fallback
                                ):
                                    headless_result = self._capture_visualization_pdf_headless(app_id, object_id)
                                    if "error" in headless_result:
                                        return _make_error(
                                            result["error"],
                                            app_id=app_id,
                                            object_id=object_id,
                                            headless_error=headless_result.get("error"),
                                            headless_details=headless_result.get("details", ""),
                                        )
                                    content = headless_result.get("content", b"")
                                    return {
                                        "app_id": app_id,
                                        "object_id": object_id,
                                        "format": "pdf",
                                        "used_headless_fallback": True,
                                        "content_type": headless_result.get("content_type", "application/pdf"),
                                        "size_bytes": len(content),
                                        "base64_pdf": base64.b64encode(content).decode("ascii"),
                                        "source_url": headless_result.get("source_url", ""),
                                        "capture_mode": headless_result.get("capture_mode", "headless"),
                                        "fallback_reason": result["error"],
                                    }
                                return {
                                    "app_id": app_id,
                                    "object_id": object_id,
                                    "format": "pdf",
                                    **(result if isinstance(result, dict) else {"result": result}),
                                }
                            raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_export_visualization_pdf)
                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif name == "engine_export_visualization_to_image":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]
                    headless_fallback = bool(arguments.get("headless_fallback", False))

                    def _export_visualization_image():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle != -1:
                                result = self.engine_api.export_visualization_to_image(app_handle, object_id)
                                if (
                                    isinstance(result, dict)
                                    and "qUrl" not in result
                                    and "error" in result
                                    and headless_fallback
                                ):
                                    headless_result = self._capture_visualization_image_headless(app_id, object_id)
                                    if "error" in headless_result:
                                        return _make_error(
                                            result["error"],
                                            app_id=app_id,
                                            object_id=object_id,
                                            headless_error=headless_result.get("error"),
                                            headless_details=headless_result.get("details", ""),
                                        )
                                    content = headless_result.get("content", b"")
                                    content_type = headless_result.get("content_type", "image/png")
                                    inferred_format = "binary"
                                    if "png" in content_type:
                                        inferred_format = "png"
                                    elif "svg" in content_type:
                                        inferred_format = "svg"
                                    elif "jpeg" in content_type or "jpg" in content_type:
                                        inferred_format = "jpeg"
                                    return {
                                        "app_id": app_id,
                                        "object_id": object_id,
                                        "format": inferred_format,
                                        "used_headless_fallback": True,
                                        "content_type": content_type,
                                        "size_bytes": len(content),
                                        "base64_image": base64.b64encode(content).decode("ascii"),
                                        "source_url": headless_result.get("source_url", ""),
                                        "capture_mode": headless_result.get("capture_mode", "headless"),
                                        "fallback_reason": result["error"],
                                    }
                                return {
                                    "app_id": app_id,
                                    "object_id": object_id,
                                    "format": "image",
                                    **(result if isinstance(result, dict) else {"result": result}),
                                }
                            raise Exception("Failed to open app")
                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_export_visualization_image)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_app_object":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]

                    def _get_app_object():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)

                            if app_handle == -1:
                                return _make_error("Failed to open app")

                            obj_result = self.engine_api.send_request("GetObject", {"qId": object_id}, handle=app_handle)
                            if "qReturn" not in obj_result:
                                return _make_error(f"Object {object_id} not found")

                            obj_handle = obj_result["qReturn"]["qHandle"]

                            layout_result = self.engine_api.send_request("GetLayout", [], handle=obj_handle)
                            if "qLayout" not in layout_result:
                                return _make_error("Failed to get object layout")

                            return layout_result

                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_app_object)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                elif name == "get_visualization_image":
                    app_id = self._resolve_app_id(arguments["app_id"])
                    object_id = arguments["object_id"]
                    requested_format = str(arguments.get("format", "auto")).lower()
                    headless_fallback = bool(arguments.get("headless_fallback", False))

                    def _get_visualization_image():
                        try:
                            self.engine_api.connect()
                            app_result = self.engine_api.open_doc(app_id, no_data=False)
                            app_handle = app_result.get("qReturn", {}).get("qHandle", -1)
                            if app_handle == -1:
                                return _make_error("Failed to open app", app_id=app_id)

                            image_ref = self.engine_api.get_visualization_image_reference(app_handle, object_id)
                            used_headless_fallback = False
                            source_url = ""
                            download_url = ""

                            if "error" in image_ref:
                                if not headless_fallback:
                                    return _make_error(
                                        image_ref["error"],
                                        app_id=app_id,
                                        object_id=object_id,
                                        object_type=image_ref.get("object_type", ""),
                                    )

                                headless_result = self._capture_visualization_image_headless(app_id, object_id)
                                if "error" in headless_result:
                                    return _make_error(
                                        image_ref.get("error", "Image extraction failed"),
                                        app_id=app_id,
                                        object_id=object_id,
                                        headless_error=headless_result.get("error"),
                                        headless_details=headless_result.get("details", ""),
                                    )

                                content = headless_result.get("content", b"")
                                content_type = headless_result.get("content_type", "image/png")
                                used_headless_fallback = True
                                source_url = headless_result.get("source_url", "")
                            else:
                                download = self._download_binary_from_qlik(image_ref["image_url"])
                                content = download.get("content", b"")
                                content_type = download.get("content_type", "application/octet-stream")
                                source_url = image_ref["image_url"]
                                download_url = download.get("download_url", "")

                            inferred_format = "binary"
                            if "png" in content_type:
                                inferred_format = "png"
                            elif "svg" in content_type:
                                inferred_format = "svg"
                            elif "jpeg" in content_type or "jpg" in content_type:
                                inferred_format = "jpeg"

                            return {
                                "app_id": app_id,
                                "object_id": object_id,
                                "object_type": image_ref.get("object_type", ""),
                                "requested_format": requested_format,
                                "format": inferred_format,
                                "used_headless_fallback": used_headless_fallback,
                                "content_type": content_type,
                                "size_bytes": len(content),
                                "base64_image": base64.b64encode(content).decode("ascii"),
                                "source_url": source_url,
                                "download_url": download_url,
                            }
                        except Exception as e:
                            return _make_error(str(e), app_id=app_id, object_id=object_id)
                        finally:
                            self.engine_api.disconnect()

                    result = await asyncio.to_thread(_get_visualization_image)
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(result, indent=2, ensure_ascii=False)
                        )
                    ]

                else:
                    return [TextContent(type="text", text=json.dumps(_make_error(f"Unknown tool: {name}"), indent=2, ensure_ascii=False))]

            except Exception as e:
                return [TextContent(type="text", text=json.dumps(_make_error(str(e)), indent=2, ensure_ascii=False))]

    async def run(self):
        """
        Start the MCP server with stdio transport.

        Initializes server capabilities and begins listening for MCP protocol messages
        over stdin/stdout for communication with MCP clients.
        """
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="qlik-sense-mcp-server",
                    server_version=__version__,
                    capabilities=ServerCapabilities(
                        tools={}
                    ),
                ),
            )


async def async_main():
    """
    Async main entry point for the Qlik Sense MCP Server.

    Creates and starts the MCP server instance with configured
    Qlik Sense Repository and Engine API connections.
    """
    server = QlikSenseMCPServer()
    await server.run()


def main():
    """
    Synchronous entry point for CLI usage.

    This function is used as the entry point in pyproject.toml
    for the qlik-sense-mcp-server command.
    """
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--help", "-h"]:
            print_help()
            return
        elif sys.argv[1] in ["--version", "-v"]:
            sys.stderr.write(f"qlik-sense-mcp-server {__version__}\n")
            sys.stderr.flush()
            return

    asyncio.run(async_main())


def print_help():
    """Print help information using logging instead of print."""
    help_text = """
Qlik Sense MCP Server - Model Context Protocol server for Qlik Sense Enterprise APIs

USAGE:
    qlik-sense-mcp-server [OPTIONS]
    uvx qlik-sense-mcp-server [OPTIONS]

OPTIONS:
    -h, --help     Show this help message
    -v, --version  Show version information

CONFIGURATION:
    Set these environment variables before running:

    QLIK_SERVER_URL       - Qlik Sense server URL (required)
                           Example: https://qlik.company.com

    QLIK_USER_DIRECTORY   - User directory (required)
                           Example: COMPANY

    QLIK_USER_ID          - User ID (required)
                           Example: your-username

    QLIK_CLIENT_CERT_PATH - Path to client certificate (required)
                           Example: /path/to/certs/client.pem

    QLIK_CLIENT_KEY_PATH  - Path to client key (required)
                           Example: /path/to/certs/client_key.pem

    QLIK_CA_CERT_PATH     - Path to CA certificate (required)
                           Example: /path/to/certs/root.pem

    QLIK_REPOSITORY_PORT  - Repository API port (optional, default: 4242)
    QLIK_ENGINE_PORT      - Engine API port (optional, default: 4747)
    QLIK_HTTP_PORT        - HTTP API port for metadata requests (optional)
    QLIK_VERIFY_SSL       - Verify SSL certificates (optional, default: true)

EXAMPLES:
    # Using uvx with environment variables
    uvx --with-env QLIK_SERVER_URL=https://qlik.company.com \\
        --with-env QLIK_USER_DIRECTORY=COMPANY \\
        --with-env QLIK_USER_ID=username \\
        --with-env QLIK_CLIENT_CERT_PATH=/path/to/client.pem \\
        --with-env QLIK_CLIENT_KEY_PATH=/path/to/client_key.pem \\
        --with-env QLIK_CA_CERT_PATH=/path/to/root.pem \\
        qlik-sense-mcp-server

    # Using environment file
    export QLIK_SERVER_URL=https://qlik.company.com
    export QLIK_USER_DIRECTORY=COMPANY
    export QLIK_USER_ID=username
    qlik-sense-mcp-server

AVAILABLE TOOLS:
    Repository API: get_apps, get_app_details, get_app_reload_chain, get_app_objects_detailed
    Engine API: get_app_sheets, get_app_sheet_objects, get_app_script, get_app_field, get_app_variables, get_app_field_statistics, engine_create_hypercube, get_app_object, get_visualization_image, engine_get_field_info, engine_extract_data, engine_get_visualization_data, engine_search_and_analyze, engine_get_master_items, engine_calculate_expression, engine_get_associations, engine_smart_search, engine_create_pivot_analysis, engine_create_simple_table, engine_get_chart_data, engine_export_visualization_to_csv, engine_export_visualization_to_xlsx, engine_export_visualization_to_pdf, engine_export_visualization_to_image

    Total: 28 tools for Qlik Sense analytics operations

MORE INFO:
    GitHub: https://github.com/data4prime/qlik-sense-mcp-d4p
    PyPI: https://pypi.org/project/qlik-sense-mcp-server/
"""
    # Use stderr for help output to avoid mixing with MCP protocol output
    sys.stderr.write(help_text + "\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
