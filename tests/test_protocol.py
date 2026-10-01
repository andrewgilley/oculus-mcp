"""Exercise the real MCP SDK client/server over both supported transports."""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
ARGS = ["-m", "oculus_mcp.server", "--state-file", str(ROOT / "examples/state.json"),
        "--tracking-file", str(ROOT / "examples/tracking.json")]


def environment():
    return {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def loopback_client(**kwargs):
    # These tests connect only to our own loopback process, never an external service.
    return httpx.AsyncClient(**kwargs, trust_env=False, follow_redirects=True)


async def exercise(session):
    await session.initialize()
    tools = (await session.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "list_tracked_projects", "list_saved_items", "list_inspections", "get_inspection_context"}
    assert all(tool.annotations.readOnlyHint and not tool.annotations.openWorldHint for tool in tools)
    assert all(tool.outputSchema for tool in tools)
    projects = await session.call_tool("list_tracked_projects", {"limit": 2})
    assert not projects.isError
    assert projects.structuredContent["total"] == 3
    assert len(projects.structuredContent["projects"]) == 2
    saved = await session.call_tool("list_saved_items", {})
    assert saved.structuredContent["total"] == 1
    inspections = await session.call_tool("list_inspections", {})
    key = inspections.structuredContent["inspections"][0]["inspection_id"]
    context = await session.call_tool("get_inspection_context", {"inspection_id": key})
    assert context.structuredContent["source"] == "cached_overview"
    invalid = await session.call_tool("list_saved_items", {"limit": 1000})
    assert invalid.isError
    missing = await session.call_tool("get_inspection_context", {"inspection_id": "../secret"})
    assert missing.isError


def test_stdio_roundtrip():
    async def run():
        async with asyncio.timeout(15):
            params = StdioServerParameters(command=sys.executable, args=ARGS, env=environment())
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await exercise(session)
    asyncio.run(run())


def test_http_roundtrip():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, *ARGS, "--transport", "streamable-http", "--port", str(port)],
        env=environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    async def run():
        async with asyncio.timeout(15):
            async with loopback_client() as client:
                while True:
                    if process.poll() is not None:
                        raise AssertionError("HTTP server exited before startup")
                    try:
                        await client.get(f"http://127.0.0.1:{port}/mcp")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
            async with loopback_client() as client:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=client) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await exercise(session)
    try:
        asyncio.run(run())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
