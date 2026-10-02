# Oculus MCP

A working, read-only MCP skeleton for [oculus.nvim](https://github.com/andrewgilley/oculus.nvim) and its future ChatGPT/Codex plugin. It uses the official Python MCP SDK and reads Oculus's existing JSON files without requiring Neovim to be running.

## Current capabilities

| Tool | Result |
| --- | --- |
| `list_tracked_projects` | GitHub/Codeberg repositories, nested tracking groups, and optional tracked subdirectory |
| `list_saved_items` | Saved activity metadata in Oculus's saved order |
| `list_inspections` | IDs of persisted inspection overviews |
| `get_inspection_context` | Cached AI explanation and up to three suggested patch locations |

All tools return structured outputs with schemas and read-only annotations. Lists support `offset` and `limit` (maximum 50). Files are reread on each request. Unknown state fields, tokens, raw event payloads, and telemetry are excluded from results.

Two read-only MCP resources provide Slack provisioning references: `oculus://slack/workspace-creation` and `oculus://slack/group-creation`. They give the Slack method names, required scopes, JSON field names, and example payloads for an Oculus organization, channel, and @mention user group. Actual organization-specific plans live behind Oculus Web's authenticated `GET /api/organizations/:id/slack-plan` endpoint. The local MCP server does not expose private organization records, hold Slack tokens, or create Slack objects.

Inspection context is **cached AI output**, possibly stale. Oculus persists explanations and suggested locations in `inspect_overviews`; that cache is not a snapshot of live buffers, complete diffs, or review threads. The adapter does not fetch forge APIs, execute commands from tool arguments, create worktrees, open editors, or modify Oculus state.

## Run the synthetic demo

Install [uv](https://docs.astral.sh/uv/) and Python 3.11 or later, then run from this repository:

```sh
uv sync --frozen
uv run oculus-mcp --state-file examples/state.json --tracking-file examples/tracking.json
```

This starts the stdio server; silence is expected until an MCP client connects. `examples/state.json` contains synthetic review metadata. Its issue URL is illustrative and is not evidence that a real issue exists.

For MCP Inspector, start loopback HTTP in one terminal:

```sh
uv run oculus-mcp --transport streamable-http --state-file examples/state.json --tracking-file examples/tracking.json
```

Then launch Inspector and select Streamable HTTP at `http://127.0.0.1:8787/mcp`:

```sh
npx @modelcontextprotocol/inspector
```

Example requests: “Which projects do I track?”, “Show my saved review items”, and “List my cached inspections, then explain the first one and identify what is unverified.”

## Connect real Oculus files

By default the server reads `$XDG_STATE_HOME/nvim/oculus.json`, falling back to `~/.local/state/nvim/oculus.json`. Match Oculus's configured `state_file` if it differs. The external tracking file is opt-in, matching Oculus's own `tracking_file` behavior:

```sh
export OCULUS_STATE_FILE="$HOME/.local/state/nvim/oculus.json"
export OCULUS_TRACKING_FILE="$HOME/.config/oculus/tracking.json"
uv run oculus-mcp
```

Without an explicit tracking file the adapter reads persisted legacy project membership from the state file. It cannot see unsaved setup options or changes that have not been persisted. An explicitly configured missing or malformed tracking file returns an error; it never silently falls back to stale state membership. Tracking version 1 and nested groups are supported; custom metadata is ignored. This reader projects known fields, rather than replacing Oculus's full tracking validation or write logic.

## Local Codex connection

Register the adapter directly from a checkout:

```sh
codex mcp add oculus -- uv --directory /absolute/path/to/oculus-mcp run --frozen oculus-mcp --state-file /absolute/path/to/oculus.json --tracking-file /absolute/path/to/tracking.json
```

For a demo connection use absolute paths to this repository's example files. Omit `--tracking-file` when Oculus uses legacy state membership.

## Plugin package

`plugin.json` and `mcp.json` provide the portable Agent Plugins layout with OpenAI presentation metadata and a local stdio server. Install the console entrypoint into a persistent tool environment so the plugin host can locate it:

```sh
uv tool install /absolute/path/to/oculus-mcp
```

Ensure `oculus-mcp` is on the plugin host's PATH, and configure the file paths in its environment or in `mcp.json` arguments. This is a development package, not a published OpenAI directory plugin. Availability of local package installation varies by client.

The HTTP mode binds only to `127.0.0.1`. It has no OAuth or user isolation and must not be forwarded to a public endpoint with real Oculus data. A public ChatGPT plugin needs an authenticated, stable HTTPS service and per-user storage. Secure MCP Tunnel is a possible private developer-mode route, but does not alone satisfy public submission requirements.

## Architecture and next steps

`models.py` defines stable output contracts. `backend.py` reads configured files and projects known fields. `server.py` exposes the tools through the official MCP SDK. The backend boundary can later support a companion bridge or hosted store without changing the tool names.

A next iteration can add an explicitly configured Neovim bridge for live inspection exports and a separately permissioned editor-open action. Rich context should include the exact commit, source URL, capture time, changed files, and review threads. Never accept arbitrary Lua or shell expressions as tool input. Current suggested file paths are labels returned to the client, not files the server opens.

A hosted version can add account isolation, authorization, GitHub/Codeberg ingestion, and event delivery for monitoring by dots. A ChatGPT panel can display saved items and inspection evidence after the core tools work. Ontology relationships can be introduced behind the backend boundary once useful cross-forge workflows are established. None of these future capabilities is claimed to work in this skeleton.

## Verification

```sh
uv sync --frozen
uv run pytest
uv build
```

Tests cover tracking precedence, nested groups, pagination, malformed and oversized files, field projection, unsafe URLs and paths, cache limitations, and real MCP initialization/tool calls over stdio and HTTP. CI runs the suite on Python 3.11, 3.12, and 3.13. The package has not yet been installed or reviewed in ChatGPT's plugin directory.

## Source contracts and references

The adapter was grounded in Oculus's `docs/tracking.md`, `lua/oculus/storage.lua`, `lua/oculus/saved.lua`, `lua/oculus/window/saved.lua`, and `lua/oculus/inspect/overview.lua` on October 1, 2026. These are JSON compatibility boundaries, not a promise that Oculus internals will never change.

[OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server) explains tools and production transport requirements. [Package your plugin](https://developers.openai.com/plugins/build/plugins) describes the portable manifest. [Plugin Extensions](https://developers.openai.com/plugins/build/extensions) and [MCP Events](https://developers.openai.com/plugins/build/mcp-events) cover later UI and event integrations.

## License

MIT. This is an independent Oculus integration and is not made or endorsed by OpenAI.
