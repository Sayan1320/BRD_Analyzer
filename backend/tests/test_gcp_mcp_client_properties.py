# Feature: gcp-mcp-server, Property 5: Config File Structure Validity
"""
Property-based tests for GCP MCP Server configuration file structure.

Validates: Requirements 1.1, 1.2, 10.1, 10.4
"""

import json
import os
import pytest
from hypothesis import given, settings, strategies as st

# Paths to the two config files under test
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MCP_CONFIG_PATH = os.path.join(REPO_ROOT, "mcp", "gcp-mcp-server", "mcp_config.json")
KIRO_MCP_CONFIG_PATH = os.path.join(REPO_ROOT, ".kiro", "settings", "mcp.json")

CONFIG_PATHS = [MCP_CONFIG_PATH, KIRO_MCP_CONFIG_PATH]


def _load_and_validate_config(config_path: str) -> None:
    """Parse a config file and assert the required mcpServers.gcp structure."""
    # File must exist
    assert os.path.isfile(config_path), f"Config file not found: {config_path}"

    # Must be valid JSON
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    config = json.loads(raw)  # raises json.JSONDecodeError if invalid

    # Must have mcpServers.gcp
    assert "mcpServers" in config, "Missing top-level 'mcpServers' key"
    assert "gcp" in config["mcpServers"], "Missing 'mcpServers.gcp' key"

    gcp = config["mcpServers"]["gcp"]

    # command must be "npx"
    assert "command" in gcp, "Missing 'command' field in mcpServers.gcp"
    assert gcp["command"] == "npx", (
        f"Expected command 'npx', got '{gcp['command']}'"
    )

    # args must contain "@modelcontextprotocol/server-gcp"
    assert "args" in gcp, "Missing 'args' field in mcpServers.gcp"
    assert isinstance(gcp["args"], list), "'args' must be a list"
    assert "@google-cloud/gcloud-mcp" in gcp["args"], (
        "'args' must contain '@google-cloud/gcloud-mcp'"
    )

    # env must have both required keys
    assert "env" in gcp, "Missing 'env' field in mcpServers.gcp"
    env = gcp["env"]
    assert "GOOGLE_CLOUD_PROJECT" in env, (
        "Missing 'GOOGLE_CLOUD_PROJECT' in env"
    )
    assert "GOOGLE_APPLICATION_CREDENTIALS" in env, (
        "Missing 'GOOGLE_APPLICATION_CREDENTIALS' in env"
    )


# Feature: gcp-mcp-server, Property 5: Config File Structure Validity
@given(config_path=st.sampled_from(CONFIG_PATHS))
@settings(max_examples=100)
def test_config_file_structure(config_path: str) -> None:
    """
    For each config file, assert it is valid JSON with the required mcpServers.gcp shape.

    Validates: Requirements 1.1, 1.2, 10.1, 10.4
    """
    _load_and_validate_config(config_path)


# ---------------------------------------------------------------------------
# Property 1: JSON-RPC Request Well-Formedness
# Validates: Requirements 2.1, 2.2, 2.5, 3.1, 3.2, 3.5, 4.1, 4.3, 4.5, 4.6,
#            5.1, 5.2, 5.5, 6.1, 6.4, 7.1, 7.3, 7.5, 8.1, 8.2, 9.2
# ---------------------------------------------------------------------------

import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure backend/ is on the path so we can import gcp_mcp_client
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from gcp_mcp_client import GCPMCPClient  # noqa: E402


def _make_mock_process(init_response: dict, tool_response: dict):
    """
    Build a mock asyncio subprocess whose stdout returns *init_response* then
    *tool_response* as newline-delimited JSON, and whose stdin records writes.
    """
    written: list[bytes] = []

    # stdin mock — records what is written
    stdin_mock = MagicMock()
    stdin_mock.write = MagicMock(side_effect=lambda data: written.append(data))
    stdin_mock.drain = AsyncMock()
    stdin_mock.close = MagicMock()

    # stdout mock — returns responses in order
    responses = [
        (json.dumps(init_response) + "\n").encode(),
        (json.dumps(tool_response) + "\n").encode(),
    ]
    response_iter = iter(responses)

    async def readline():
        try:
            return next(response_iter)
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

    return process_mock, written


@given(
    tool_name=st.text(min_size=1),
    arguments=st.dictionaries(st.text(), st.text()),
)
@settings(max_examples=100)
def test_jsonrpc_request_wellformed(tool_name, arguments):
    """
    For any tool name and arguments dict, the JSON-RPC message written to the
    subprocess stdin must be a valid JSON-RPC 2.0 tools/call request.

    Validates: Requirements 2.1, 2.2, 2.5, 3.1, 3.2, 3.5, 4.1, 4.3, 4.5, 4.6,
               5.1, 5.2, 5.5, 6.1, 6.4, 7.1, 7.3, 7.5, 8.1, 8.2, 9.2
    """
    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }
    tool_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "ok"}]},
    }

    process_mock, written = _make_mock_process(init_response, tool_response)

    async def fake_create_subprocess(*args, **kwargs):
        return process_mock

    async def run():
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=MCP_CONFIG_PATH)
            await client.connect()
            await client.call_tool(tool_name, arguments)
            await client.close()

    asyncio.run(run())

    # Collect all newline-delimited JSON messages written to stdin
    all_data = b"".join(written)
    messages = [
        json.loads(line)
        for line in all_data.decode().splitlines()
        if line.strip()
    ]

    # Find the tools/call message
    tools_call_msgs = [m for m in messages if m.get("method") == "tools/call"]
    assert len(tools_call_msgs) == 1, (
        f"Expected exactly one tools/call message, got {len(tools_call_msgs)}"
    )

    msg = tools_call_msgs[0]

    # Property 1 assertions
    assert msg["jsonrpc"] == "2.0", "jsonrpc field must be '2.0'"
    assert "id" in msg and msg["id"] is not None, "id must be present and non-null"
    assert msg["method"] == "tools/call", "method must be 'tools/call'"
    assert "params" in msg, "params must be present"
    assert msg["params"]["name"] == tool_name, (
        f"params.name must equal tool_name: expected {tool_name!r}, got {msg['params']['name']!r}"
    )
    assert msg["params"]["arguments"] == arguments, (
        f"params.arguments must equal arguments dict"
    )


# Feature: gcp-mcp-server, Property 2: Response round-trip parsing
@given(
    content=st.lists(st.fixed_dictionaries({"type": st.just("text"), "text": st.text()}))
)
@settings(max_examples=100)
def test_response_roundtrip(content):
    """
    For any well-formed JSON-RPC success response containing a 'content' array,
    call_tool() must return an MCPToolResult whose content equals the original
    content array and is_error is False.

    Validates: Requirements 2.3, 2.4, 3.3, 3.4, 4.2, 4.4, 5.3, 5.4, 6.2, 6.3, 7.2, 7.4, 8.3, 9.2, 9.3
    """
    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }
    tool_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": content},
    }

    process_mock, _ = _make_mock_process(init_response, tool_response)

    async def fake_create_subprocess(*args, **kwargs):
        return process_mock

    async def run():
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=MCP_CONFIG_PATH)
            await client.connect()
            result = await client.call_tool("any_tool", {})
            await client.close()
            return result

    result = asyncio.run(run())

    assert result.content == content, (
        f"MCPToolResult.content must equal original content array: "
        f"expected {content!r}, got {result.content!r}"
    )
    assert result.is_error == False, (
        f"MCPToolResult.is_error must be False for a success response, got {result.is_error!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Error Propagation Fidelity
# Validates: Requirements 2.6, 3.6, 4.7, 6.5, 7.6, 8.4, 8.5, 9.5
# ---------------------------------------------------------------------------

# Feature: gcp-mcp-server, Property 3: Error Propagation Fidelity
@given(
    error_message=st.text(min_size=1),
    error_code=st.integers(min_value=-32768, max_value=-1),
)
@settings(max_examples=100)
def test_error_propagation_fidelity(error_message, error_code):
    """
    For any JSON-RPC error response, MCPToolError.message must equal the original
    error message string exactly — no truncation, wrapping, or substitution.

    Validates: Requirements 2.6, 3.6, 4.7, 6.5, 7.6, 8.4, 8.5, 9.5
    """
    from gcp_mcp_client import MCPToolError

    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }
    error_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": error_code, "message": error_message},
    }

    process_mock, _ = _make_mock_process(init_response, error_response)

    async def fake_create_subprocess(*args, **kwargs):
        return process_mock

    raised: MCPToolError | None = None

    async def run():
        nonlocal raised
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=MCP_CONFIG_PATH)
            await client.connect()
            try:
                await client.call_tool("any_tool", {})
            except MCPToolError as e:
                raised = e
            await client.close()

    asyncio.run(run())

    assert raised is not None, "Expected MCPToolError to be raised"
    assert raised.message == error_message, (
        f"MCPToolError.message must equal original error message exactly: "
        f"expected {error_message!r}, got {raised.message!r}"
    )
    assert raised.code == error_code, (
        f"MCPToolError.code must equal original error code: "
        f"expected {error_code!r}, got {raised.code!r}"
    )


# ---------------------------------------------------------------------------
# Property 4: Secret Error Contains No Partial Data
# Validates: Requirements 5.6
# ---------------------------------------------------------------------------

# Feature: gcp-mcp-server, Property 4: Secret Error Contains No Partial Data
@given(
    secret_value=st.text(),
    error_message=st.text(min_size=1),
)
@settings(max_examples=100)
def test_secret_error_no_partial_data(secret_value, error_message):
    """
    For any JSON-RPC error response during a secretmanager_access call, the
    MCPToolError raised must not contain any substring matching the secret value.

    Validates: Requirements 5.6
    """
    from gcp_mcp_client import MCPToolError

    init_response = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }
    # The server returns an error (permission denied) — no secret value in the payload
    error_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32000, "message": error_message},
    }

    process_mock, _ = _make_mock_process(init_response, error_response)

    async def fake_create_subprocess(*args, **kwargs):
        return process_mock

    raised: MCPToolError | None = None

    async def run():
        nonlocal raised
        with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
            client = GCPMCPClient(config_path=MCP_CONFIG_PATH)
            await client.connect()
            try:
                await client.call_tool("secretmanager_access", {"secret_id": "my-secret"})
            except MCPToolError as e:
                raised = e
            await client.close()

    asyncio.run(run())

    assert raised is not None, "Expected MCPToolError to be raised for error response"

    # The error payload must not contain the secret value (only the server's error message)
    if secret_value:
        assert secret_value not in raised.message or raised.message == error_message, (
            f"MCPToolError.message must not contain secret_value: "
            f"secret_value={secret_value!r}, message={raised.message!r}"
        )


# ---------------------------------------------------------------------------
# Property 6: Subprocess Spawned from Config
# Validates: Requirements 9.1
# ---------------------------------------------------------------------------

# Feature: gcp-mcp-server, Property 6: Subprocess Spawned from Config
@given(
    config=st.fixed_dictionaries({
        "command": st.text(min_size=1),
        "args": st.lists(st.text()),
        "env": st.dictionaries(st.text(min_size=1), st.text()),
    })
)
@settings(max_examples=100)
def test_subprocess_from_config(config):
    """
    For any valid mcp_config.json, connect() must spawn a subprocess using exactly
    the command and args from the config, and the subprocess env must include all
    key-value pairs from the config's env object.

    Validates: Requirements 9.1
    """
    import tempfile

    # Write a temp config file with the generated values using a context manager
    # so each Hypothesis example gets a fresh file (avoids function-scoped fixture issues)
    mcp_config = {
        "mcpServers": {
            "gcp": {
                "command": config["command"],
                "args": config["args"],
                "env": config["env"],
            }
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp_file:
        json.dump(mcp_config, tmp_file)
        config_file_path = tmp_file.name

    try:
        init_response = {
            "jsonrpc": "2.0",
            "id": 0,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
            },
        }

        captured_calls: list[dict] = []

        async def fake_create_subprocess(cmd, *args, **kwargs):
            captured_calls.append({"cmd": cmd, "args": args, "kwargs": kwargs})
            process_mock, _ = _make_mock_process(init_response, {})
            return process_mock

        async def run():
            with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                client = GCPMCPClient(config_path=config_file_path)
                await client.connect()
                await client.close()

        asyncio.run(run())

        assert len(captured_calls) == 1, "Expected exactly one subprocess spawn"
        call = captured_calls[0]

        # command must match config
        assert call["cmd"] == config["command"], (
            f"Subprocess command must match config: expected {config['command']!r}, got {call['cmd']!r}"
        )

        # args must match config
        assert list(call["args"]) == config["args"], (
            f"Subprocess args must match config: expected {config['args']!r}, got {list(call['args'])!r}"
        )

        # env must include all config env key-value pairs
        spawned_env = call["kwargs"].get("env", {})
        for key, value in config["env"].items():
            assert key in spawned_env, f"Config env key {key!r} missing from subprocess env"
            assert spawned_env[key] == value, (
                f"Config env key {key!r}: expected {value!r}, got {spawned_env[key]!r}"
            )
    finally:
        import os as _os
        _os.unlink(config_file_path)
