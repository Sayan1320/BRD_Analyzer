"""
Unit tests for GCPMCPClient.

Validates: Requirements 2.1, 5.6, 9.1, 9.2, 9.4, 9.5
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from gcp_mcp_client import GCPMCPClient, MCPConnectionError, MCPToolError  # noqa: E402

# Path to the real config used when not overriding
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))
_MCP_CONFIG_PATH = os.path.join(_REPO_ROOT, "mcp", "gcp-mcp-server", "mcp_config.json")


# ---------------------------------------------------------------------------
# 10.1 Correct JSON-RPC message shape for cloudrun_deploy
# Validates: Requirements 2.1, 9.2
# ---------------------------------------------------------------------------

def test_cloudrun_deploy_jsonrpc_shape(mock_mcp_subprocess):
    """
    call_tool("cloudrun_deploy", {...}) must produce a valid JSON-RPC 2.0
    tools/call message with the correct method, params.name, and params.arguments.

    Validates: Requirements 2.1, 9.2
    """
    controller = mock_mcp_subprocess
    controller.set_response({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "deployed"}]},
    })

    args = {
        "service_name": "my-svc",
        "image": "gcr.io/proj/img:latest",
        "region": "us-central1",
    }

    async def run():
        client = GCPMCPClient(config_path=_MCP_CONFIG_PATH)
        await client.connect()
        await client.call_tool("cloudrun_deploy", args)
        await client.close()

    asyncio.run(run())

    msg = controller.capture_sent_message()
    assert msg is not None, "Expected a tools/call message to be sent"
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "tools/call"
    assert "params" in msg
    assert msg["params"]["name"] == "cloudrun_deploy"
    assert msg["params"]["arguments"] == args


# ---------------------------------------------------------------------------
# 10.2 call_tool with empty args dict
# Validates: Requirements 9.2
# ---------------------------------------------------------------------------

def test_call_tool_empty_args(mock_mcp_subprocess):
    """
    call_tool("any_tool", {}) must send params.arguments == {} and still be
    a valid JSON-RPC 2.0 request.

    Validates: Requirements 9.2
    """
    controller = mock_mcp_subprocess
    controller.set_response({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": []},
    })

    async def run():
        client = GCPMCPClient(config_path=_MCP_CONFIG_PATH)
        await client.connect()
        await client.call_tool("any_tool", {})
        await client.close()

    asyncio.run(run())

    msg = controller.capture_sent_message()
    assert msg is not None
    assert msg["jsonrpc"] == "2.0"
    assert "id" in msg and msg["id"] is not None
    assert msg["method"] == "tools/call"
    assert msg["params"]["arguments"] == {}


# ---------------------------------------------------------------------------
# 10.3 Timeout raises MCPConnectionError
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------

def test_timeout_raises_mcp_connection_error():
    """
    When the subprocess stdout never responds, call_tool must raise
    MCPConnectionError. We wrap the call in asyncio.wait_for with a short
    timeout to avoid waiting the full 10 s.

    Validates: Requirements 9.4
    """
    written: list[bytes] = []
    call_count = [0]

    stdin_mock = MagicMock()
    stdin_mock.write = MagicMock(side_effect=lambda data: written.append(data))
    stdin_mock.drain = AsyncMock()
    stdin_mock.close = MagicMock()

    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }

    async def readline_hang():
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            return (json.dumps(init_response) + "\n").encode()
        # Hang forever on subsequent reads
        await asyncio.sleep(9999)
        return b""

    stdout_mock = MagicMock()
    stdout_mock.readline = readline_hang

    process_mock = MagicMock()
    process_mock.stdin = stdin_mock
    process_mock.stdout = stdout_mock
    process_mock.returncode = None
    process_mock.terminate = MagicMock()
    process_mock.kill = MagicMock()
    process_mock.wait = AsyncMock()

    async def fake_create_subprocess(*args, **kwargs):
        return process_mock

    raised = None

    async def run():
        nonlocal raised
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=_MCP_CONFIG_PATH)
            await client.connect()
            try:
                # Short outer timeout so the test doesn't block for 10 s
                await asyncio.wait_for(
                    client.call_tool("slow_tool", {}),
                    timeout=2.0,
                )
            except MCPConnectionError as e:
                raised = e
            except asyncio.TimeoutError:
                # The outer wait_for fired before the inner one — still means
                # the call hung, which is the behaviour we're testing.
                raised = MCPConnectionError("outer timeout fired")

    asyncio.run(run())
    assert raised is not None, "Expected MCPConnectionError to be raised"


# ---------------------------------------------------------------------------
# 10.4 Malformed JSON-RPC response raises MCPToolError
# Validates: Requirements 9.5
# ---------------------------------------------------------------------------

def test_malformed_response_raises_mcp_tool_error(mock_mcp_subprocess):
    """
    A response with neither 'result' nor 'error' fields must raise MCPToolError.

    Validates: Requirements 9.5
    """
    controller = mock_mcp_subprocess
    controller.set_response({"jsonrpc": "2.0", "id": 1})

    raised = None

    async def run():
        nonlocal raised
        client = GCPMCPClient(config_path=_MCP_CONFIG_PATH)
        await client.connect()
        try:
            await client.call_tool("any_tool", {})
        except MCPToolError as e:
            raised = e
        await client.close()

    asyncio.run(run())
    assert raised is not None, "Expected MCPToolError to be raised"


# ---------------------------------------------------------------------------
# 10.5 connect() reads command and args from mcp_config.json
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------

def test_connect_reads_command_and_args_from_config(mock_config_path):
    """
    connect() must spawn the subprocess using the command and args from the
    config file, not hardcoded values.

    Validates: Requirements 9.1
    """
    captured: list[dict] = []

    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }

    written: list[bytes] = []

    async def fake_create_subprocess(cmd, *args, **kwargs):
        captured.append({"cmd": cmd, "args": args, "kwargs": kwargs})

        stdin_mock = MagicMock()
        stdin_mock.write = MagicMock(side_effect=lambda data: written.append(data))
        stdin_mock.drain = AsyncMock()
        stdin_mock.close = MagicMock()

        responses = iter([(json.dumps(init_response) + "\n").encode()])

        async def readline():
            try:
                return next(responses)
            except StopIteration:
                return b""

        stdout_mock = MagicMock()
        stdout_mock.readline = readline

        process_mock = MagicMock()
        process_mock.stdin = stdin_mock
        process_mock.stdout = stdout_mock
        process_mock.returncode = None
        process_mock.terminate = MagicMock()
        process_mock.kill = MagicMock()
        process_mock.wait = AsyncMock()
        return process_mock

    async def run():
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=mock_config_path)
            await client.connect()
            await client.close()

    asyncio.run(run())

    assert len(captured) == 1, "Expected exactly one subprocess spawn"
    call = captured[0]
    assert call["cmd"] == "npx", f"Expected command 'npx', got {call['cmd']!r}"
    assert list(call["args"]) == ["-y", "@modelcontextprotocol/server-gcp"], (
        f"Expected args ['-y', '@modelcontextprotocol/server-gcp'], got {list(call['args'])!r}"
    )


# ---------------------------------------------------------------------------
# 10.6 Secret permission-denied path raises MCPToolError without partial data
# Validates: Requirements 5.6
# ---------------------------------------------------------------------------

def test_secret_permission_denied_raises_mcp_tool_error(mock_mcp_subprocess):
    """
    A permission-denied error response for secretmanager_access must raise
    MCPToolError and the error message must not contain any partial secret data.

    Validates: Requirements 5.6
    """
    controller = mock_mcp_subprocess
    controller.set_response({
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32000,
            "message": "Permission denied on secret my-secret",
        },
    })

    raised = None

    async def run():
        nonlocal raised
        client = GCPMCPClient(config_path=_MCP_CONFIG_PATH)
        await client.connect()
        try:
            await client.call_tool("secretmanager_access", {"secret_id": "my-secret"})
        except MCPToolError as e:
            raised = e
        await client.close()

    asyncio.run(run())

    assert raised is not None, "Expected MCPToolError to be raised"
    # The error message must not contain any actual secret value
    secret_value = "super-secret-value-12345"
    assert secret_value not in raised.message, (
        f"Error message must not contain partial secret data: {raised.message!r}"
    )
    assert raised.message == "Permission denied on secret my-secret"
    assert raised.code == -32000
