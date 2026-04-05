"""Live integration test for the public MCP tools against a configured Qlik environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from mcp.types import CallToolRequest, ListToolsRequest

from qlik_sense_mcp_server.server import QlikSenseMCPServer


pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"
EXPECTED_TOOL_NAMES = {
    "get_apps",
    "get_app_details",
    "get_app_script",
    "get_app_field_statistics",
    "engine_create_hypercube",
    "get_app_field",
    "get_app_variables",
    "get_app_sheets",
    "get_app_sheet_objects",
    "get_app_object",
}


def _live_tests_enabled() -> bool:
    return os.getenv("RUN_QLIK_LIVE_TESTS", "").strip().lower() in {"1", "true", "yes", "y"}


if not _live_tests_enabled():
    pytest.skip(
        "Set RUN_QLIK_LIVE_TESTS=1 to run live MCP integration tests against Qlik",
        allow_module_level=True,
    )


def _load_live_env() -> dict[str, str]:
    if not ENV_FILE.is_file():
        pytest.fail(f"Missing required env file for live tests: {ENV_FILE}")

    loaded = {
        key: value
        for key, value in dotenv_values(ENV_FILE).items()
        if key and value is not None
    }

    cert_dir_value = loaded.get("QLIK_CERTS_DIR", "./certs")
    cert_dir = Path(cert_dir_value)
    if not cert_dir.is_absolute():
        cert_dir = (REPO_ROOT / cert_dir).resolve()

    for env_name in ("QLIK_CLIENT_CERT_PATH", "QLIK_CLIENT_KEY_PATH", "QLIK_CA_CERT_PATH"):
        configured_path = loaded.get(env_name)
        if not configured_path:
            continue

        candidate = Path(configured_path)
        if candidate.is_file():
            loaded[env_name] = str(candidate)
            continue

        if configured_path.startswith("/certs/"):
            local_candidate = cert_dir / candidate.name
        elif not candidate.is_absolute():
            local_candidate = (REPO_ROOT / candidate).resolve()
        else:
            local_candidate = candidate

        if not local_candidate.is_file():
            pytest.fail(
                f"{env_name} points to a missing file for live tests: {configured_path} -> {local_candidate}"
            )

        loaded[env_name] = str(local_candidate)

    return loaded


def _extract_json_payload(result: Any) -> dict[str, Any]:
    root = getattr(result, "root", None)
    if root is None:
        pytest.fail(f"MCP handler returned unexpected result without root: {result!r}")

    content = getattr(root, "content", None) or []
    if not content:
        pytest.fail(f"MCP handler returned empty content payload: {root!r}")

    text_content = getattr(content[0], "text", None)
    if not text_content:
        pytest.fail(f"MCP handler returned non-text content: {content!r}")

    try:
        parsed = json.loads(text_content)
    except json.JSONDecodeError as exc:
        pytest.fail(f"MCP handler returned invalid JSON payload: {text_content}")

    if not isinstance(parsed, dict):
        pytest.fail(f"Expected dict payload from MCP tool, got: {type(parsed).__name__}")

    return parsed


def _pick_first(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_field_name(fields: list[Any]) -> str | None:
    preferred: list[str] = []
    fallback: list[str] = []

    for field in fields:
        if isinstance(field, str):
            candidate = field.strip()
        elif isinstance(field, dict):
            candidate = _pick_first(field, "name", "field_name", "field", "qName")
        else:
            candidate = None

        if not candidate:
            continue

        if candidate.startswith("$") or "]" in candidate:
            fallback.append(candidate)
        else:
            preferred.append(candidate)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


async def _list_public_tool_names(server: QlikSenseMCPServer) -> set[str]:
    handler = server.server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest())
    root = getattr(result, "root", None)
    tools = getattr(root, "tools", None) or []
    return {tool.name for tool in tools}


async def _call_tool(server: QlikSenseMCPServer, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = server.server.request_handlers[CallToolRequest]
    result = await handler(CallToolRequest(params={"name": name, "arguments": arguments}))
    return _extract_json_payload(result)


async def _discover_resource_bundle(server: QlikSenseMCPServer) -> dict[str, str]:
    diagnostics: list[str] = []
    app_batches = [
        await _call_tool(server, "get_apps", {"limit": 10, "published": "true"}),
        await _call_tool(server, "get_apps", {"limit": 10, "published": "false"}),
        await _call_tool(server, "get_apps", {"limit": 10}),
    ]

    apps: list[dict[str, Any]] = []
    for batch in app_batches:
        if "error" in batch:
            diagnostics.append(f"get_apps discovery error: {batch['error']}")
            continue
        for app in batch.get("apps", []):
            if app not in apps:
                apps.append(app)

    if not apps:
        pytest.fail("Live MCP test could not discover any accessible Qlik apps. " + " | ".join(diagnostics))

    for app in apps:
        app_id = _pick_first(app, "guid", "app_id", "id")
        if not app_id:
            diagnostics.append(f"Skipping app without identifier: {app}")
            continue

        details = await _call_tool(server, "get_app_details", {"app_id": app_id})
        if "error" in details:
            diagnostics.append(f"get_app_details failed for {app_id}: {details['error']}")
            continue

        field_name = _extract_field_name(details.get("fields", []))
        if not field_name:
            diagnostics.append(f"No usable field found in app {app_id}")
            continue

        sheets_payload = await _call_tool(server, "get_app_sheets", {"app_id": app_id})
        if "error" in sheets_payload:
            diagnostics.append(f"get_app_sheets failed for {app_id}: {sheets_payload['error']}")
            continue

        for sheet in sheets_payload.get("sheets", []):
            sheet_id = _pick_first(sheet, "sheet_id", "id", "qId")
            if not sheet_id:
                continue

            objects_payload = await _call_tool(
                server,
                "get_app_sheet_objects",
                {"app_id": app_id, "sheet_id": sheet_id},
            )
            if "error" in objects_payload:
                diagnostics.append(
                    f"get_app_sheet_objects failed for {app_id}/{sheet_id}: {objects_payload['error']}"
                )
                continue

            objects = objects_payload.get("objects", [])
            if not objects:
                diagnostics.append(f"Sheet {sheet_id} in app {app_id} has no objects")
                continue

            object_id = _pick_first(objects[0], "object_id", "id", "qId")
            if object_id:
                return {
                    "app_id": app_id,
                    "field_name": field_name,
                    "sheet_id": sheet_id,
                    "object_id": object_id,
                }

    pytest.fail(
        "Live MCP test could not find an app with a field, a sheet, and at least one object. "
        + " | ".join(diagnostics)
    )


@pytest.mark.asyncio
async def test_live_public_mcp_tools_from_env_configuration() -> None:
    live_env = _load_live_env()

    with patch.dict(os.environ, live_env, clear=False):
        server = QlikSenseMCPServer()

        assert server.config_valid is True, "Qlik config did not validate with the current .env settings"
        assert server.repository_api is not None, "Repository API client was not initialized"
        assert server.engine_api is not None, "Engine API client was not initialized"

        tool_names = await _list_public_tool_names(server)
        assert tool_names == EXPECTED_TOOL_NAMES

        resources = await _discover_resource_bundle(server)
        app_id = resources["app_id"]
        field_name = resources["field_name"]
        sheet_id = resources["sheet_id"]
        object_id = resources["object_id"]

        failures: list[str] = []

        apps_payload = await _call_tool(server, "get_apps", {"limit": 5, "published": "true"})
        if "error" in apps_payload:
            failures.append(f"get_apps failed: {apps_payload['error']}")
        elif not apps_payload.get("apps"):
            failures.append("get_apps returned no accessible applications")

        details_payload = await _call_tool(server, "get_app_details", {"app_id": app_id})
        if "error" in details_payload:
            failures.append(f"get_app_details failed: {details_payload['error']}")
        elif _pick_first(details_payload.get("metainfo", {}), "app_id") != app_id:
            failures.append(f"get_app_details returned unexpected app id for {app_id}")

        script_payload = await _call_tool(server, "get_app_script", {"app_id": app_id})
        if "error" in script_payload:
            failures.append(f"get_app_script failed: {script_payload['error']}")
        elif "qScript" not in script_payload:
            failures.append("get_app_script did not return qScript")

        field_stats_payload = await _call_tool(
            server,
            "get_app_field_statistics",
            {"app_id": app_id, "field_name": field_name},
        )
        if "error" in field_stats_payload:
            failures.append(f"get_app_field_statistics failed: {field_stats_payload['error']}")
        elif field_stats_payload.get("field_name") != field_name:
            failures.append(f"get_app_field_statistics returned unexpected field name for {field_name}")

        hypercube_payload = await _call_tool(
            server,
            "engine_create_hypercube",
            {
                "app_id": app_id,
                "dimensions": [{"field": field_name, "label": field_name}],
                "measures": [{"expression": f"Count([{field_name}])", "label": "RecordCount"}],
                "max_rows": 10,
            },
        )
        if "error" in hypercube_payload:
            failures.append(f"engine_create_hypercube failed: {hypercube_payload['error']}")
        elif "hypercube_data" not in hypercube_payload:
            failures.append("engine_create_hypercube did not return hypercube_data")

        field_payload = await _call_tool(
            server,
            "get_app_field",
            {"app_id": app_id, "field_name": field_name, "limit": 5},
        )
        if "error" in field_payload:
            failures.append(f"get_app_field failed: {field_payload['error']}")
        elif "field_values" not in field_payload:
            failures.append("get_app_field did not return field_values")

        variables_payload = await _call_tool(server, "get_app_variables", {"app_id": app_id, "limit": 5})
        if "error" in variables_payload:
            failures.append(f"get_app_variables failed: {variables_payload['error']}")
        elif "variables_from_script" not in variables_payload or "variables_from_ui" not in variables_payload:
            failures.append("get_app_variables did not return both script and ui sections")

        sheets_payload = await _call_tool(server, "get_app_sheets", {"app_id": app_id})
        if "error" in sheets_payload:
            failures.append(f"get_app_sheets failed: {sheets_payload['error']}")
        elif not sheets_payload.get("sheets"):
            failures.append(f"get_app_sheets returned no sheets for app {app_id}")

        sheet_objects_payload = await _call_tool(
            server,
            "get_app_sheet_objects",
            {"app_id": app_id, "sheet_id": sheet_id},
        )
        if "error" in sheet_objects_payload:
            failures.append(f"get_app_sheet_objects failed: {sheet_objects_payload['error']}")
        elif not sheet_objects_payload.get("objects"):
            failures.append(f"get_app_sheet_objects returned no objects for sheet {sheet_id}")

        object_payload = await _call_tool(
            server,
            "get_app_object",
            {"app_id": app_id, "object_id": object_id},
        )
        if "error" in object_payload:
            failures.append(f"get_app_object failed: {object_payload['error']}")
        elif "qLayout" not in object_payload:
            failures.append(f"get_app_object did not return qLayout for object {object_id}")

        assert not failures, "\n".join(failures)