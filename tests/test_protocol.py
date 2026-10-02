"""Exercise the real MCP SDK client/server over both supported transports."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

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
        "list_tracked_projects", "list_saved_items", "list_inspections", "get_inspection_context",
        "list_web_workflow_sectors", "create_web_workflow"}
    assert all(tool.annotations.readOnlyHint and not tool.annotations.openWorldHint
               for tool in tools if tool.name != "create_web_workflow")
    write_tool = next(tool for tool in tools if tool.name == "create_web_workflow")
    assert not write_tool.annotations.readOnlyHint
    assert not write_tool.annotations.destructiveHint
    assert not write_tool.annotations.idempotentHint
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
    resources = (await session.list_resources()).resources
    assert {str(resource.uri) for resource in resources} == {
        "oculus://slack/workspace-creation", "oculus://slack/group-creation"}
    workspace = json.loads((await session.read_resource("oculus://slack/workspace-creation")).contents[0].text)
    assert workspace["method"] == "admin.teams.create"
    assert set(workspace["bodyExample"]) == {
        "team_domain", "team_name", "team_description", "team_discoverability"}
    group = json.loads((await session.read_resource("oculus://slack/group-creation")).contents[0].text)
    assert [step["method"] for step in group["steps"]] == [
        "conversations.create", "usergroups.create", "usergroups.users.update"]
    assert group["steps"][1]["bodyExample"]["channels"] == "C12345678"


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


def test_workflow_creation_tool_sends_account_code_to_configured_web_api():
    seen = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == "/api/workflow-setup/import"
            seen["authorization"] = self.headers["Authorization"]
            seen["workflow"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            result = {"id": "workflow-1", "title": seen["workflow"]["title"],
                      "webUrl": "http://localhost:3000/workflows/workflow-1"}
            payload = json.dumps(result).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            assert self.path == "/api/workflow-setup/sectors"
            payload = json.dumps([{"id": "sector-1", "slug": "personal-pursuits",
                                   "name": "Personal pursuits", "description": "Private"}]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = "A" * 43
    workflow = {
        "title": "Explore research", "activity": "research", "goal": "Learn the field",
        "steps": [{"title": "Collect sources", "description": "Read primary data"}],
        "resources": [{"kind": "data", "title": "Source data", "url": "https://example.com/data"}],
    }
    async def run():
        env = {**environment(), "OCULUS_WEB_API_URL": f"http://127.0.0.1:{server.server_port}"}
        async with asyncio.timeout(15):
            params = StdioServerParameters(command=sys.executable, args=ARGS, env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    sectors = await session.call_tool("list_web_workflow_sectors", {})
                    assert not sectors.isError
                    created = await session.call_tool("create_web_workflow", {"setup_code": code, "workflow": workflow})
                    assert not created.isError
                    assert created.structuredContent["webUrl"].endswith("/workflows/workflow-1")
    try:
        asyncio.run(run())
        assert seen["authorization"] == f"Bearer {code}"
        assert seen["workflow"]["title"] == workflow["title"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
