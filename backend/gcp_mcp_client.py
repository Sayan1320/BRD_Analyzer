"""
GCP MCP Client — communicates with the GCP MCP server subprocess via stdio JSON-RPC 2.0.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MCPToolResult:
    content: list[dict]
    is_error: bool = False


@dataclass
class MCPToolError(Exception):
    code: int
    message: str


class MCPConnectionError(Exception):
    """Raised when the MCP server subprocess cannot be reached within timeout."""
    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GCPMCPClient:
    """Manages a subprocess connection to the GCP MCP server via stdio transport."""

    def __init__(self, config_path: str = "mcp/gcp-mcp-server/mcp_config.json") -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        gcp = config["mcpServers"]["gcp"]
        self._command: str = gcp["command"]
        self._args: list[str] = gcp["args"]
        self._env: dict[str, str] = gcp.get("env", {})

        self._process: asyncio.subprocess.Process | None = None
        self._request_id: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send(self, message: dict) -> None:
        """Serialize *message* as newline-delimited JSON and write to stdin."""
        if self._process is None or self._process.stdin is None:
            raise MCPConnectionError("Not connected — call connect() first")
        line = json.dumps(message) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

    async def _recv(self) -> dict:
        """Read one newline-delimited JSON line from stdout."""
        if self._process is None or self._process.stdout is None:
            raise MCPConnectionError("Not connected — call connect() first")
        line = await self._process.stdout.readline()
        if not line:
            raise MCPConnectionError("MCP server closed stdout unexpectedly")
        return json.loads(line.decode())

    def _build_env(self) -> dict[str, str]:
        """Merge current process env with config env (config values take precedence)."""
        env = dict(os.environ)
        env.update(self._env)
        return env

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Spawn the MCP server subprocess and perform JSON-RPC initialize handshake."""
        env = self._build_env()
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # JSON-RPC initialize handshake
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gcp-mcp-client", "version": "1.0.0"},
            },
        }
        await self._send(init_request)
        # Read and discard the initialize response
        await self._recv()

    async def list_tools(self) -> list[dict]:
        """Send tools/list request and return the parsed tool list."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        await self._send(request)
        response = await self._recv()
        result = response.get("result", {})
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """
        Send a tools/call JSON-RPC request and return an MCPToolResult.

        Raises:
            MCPConnectionError: if the subprocess is dead or the call times out (10 s).
            MCPToolError: if the server returns a JSON-RPC error response.
        """
        if self._process is not None and self._process.returncode is not None:
            raise MCPConnectionError(
                f"MCP server process has exited with code {self._process.returncode}"
            )

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            await asyncio.wait_for(self._send(request), timeout=10.0)
            response = await asyncio.wait_for(self._recv(), timeout=10.0)
        except asyncio.TimeoutError:
            raise MCPConnectionError(
                f"Timed out waiting for MCP server response to tool '{tool_name}'"
            )

        if "error" in response:
            err = response["error"]
            raise MCPToolError(code=err.get("code", -1), message=err.get("message", ""))

        if "result" not in response:
            raise MCPToolError(
                code=-32700,
                message=f"Parse error: response contains neither 'result' nor 'error': {response}",
            )

        result = response["result"]
        return MCPToolResult(content=result.get("content", []))

    async def close(self) -> None:
        """Terminate the MCP server subprocess cleanly."""
        if self._process is None:
            return
        try:
            if self._process.stdin:
                self._process.stdin.close()
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            self._process.kill()
        finally:
            self._process = None
