# backchannel

A single Python Claude Code plugin and MCP server that runs six token-saving and observability tools together in one process, with zero external dependencies (pure Python 3.10+ standard library).

I used Caveman, Ponytail, Headroom, Graphify, and Claude-Mem separately for a couple of months to cut down Claude Code token usage. Juggling separate plugins, configs, and commands got messy, so I combined them into one Python MCP server and local daemon, rewrote the Caveman voice rules to trim more output tokens in plain English, and added a local dashboard to control everything from one place.

## What runs inside Backchannel

- **Backchannel** — local dashboard (`http://127.0.0.1:4242`) for live session transcripts, multi-agent communication topology, filler %, and token spend
- **Caveman** — rewritten English-only output discipline (`off` | `terse` | `ultra` | `megacave`) plus a `CLAUDE.md` compressor (`backchannel compress-doc`)
- **Ponytail** — minimalism decision ladder (`off` | `lite` | `full` | `ultra`) and repo-wide redundancy audit (`backchannel audit`)
- **Headroom** — transparent local HTTP/HTTPS streaming compression proxy (`http://127.0.0.1:4243`) that shrinks repetitive tool outputs and logs in flight while preserving errors and `cache_control` breakpoints
- **Graphify** — local codebase knowledge graph (`.backchannel/graph.json`, 16+ languages + pure-Python PDF extraction) so Claude queries symbols and dependencies instead of brute-force grepping
- **Claude-Mem** — cross-session project memory with hybrid BM25 + 3-gram semantic search, automatic recall on `SessionStart`, and zero-cost session summaries on `SessionEnd`

## Requirements

- Python >= 3.10
- Zero external packages

## Install

```bash
git clone https://github.com/saiswaroopkakuru/backchannel.git
cd backchannel
pip install -e .
```

Or run without installing:

```bash
python -m backchannel all
```

To load it directly as a Claude Code plugin:

```bash
claude --plugin-dir ./backchannel
```

## Quick Start

Start everything at once (all 6 engines + dashboard + proxy + OmniRoute + Graphify index):

```bash
backchannel all
```

Inside a Claude Code terminal, run:

```text
/bc
```

To launch Claude Code routed through the local compression proxy:

```bash
# Primary upstream (auto-chains to existing ANTHROPIC_BASE_URL if configured)
backchannel claude

# Route through OmniRoute (http://127.0.0.1:4243/omni -> http://127.0.0.1:20128)
backchannel claude-omni
```

Open the dashboard at [http://127.0.0.1:4242](http://127.0.0.1:4242) to toggle modes live and monitor token savings.

## Proxy & OmniRoute Support

The local Headroom proxy runs on port `4243` and supports two routes simultaneously:

- `http://127.0.0.1:4243` — forwards to your primary upstream (auto-detected from `~/.claude/settings.json` or `https://api.anthropic.com`)
- `http://127.0.0.1:4243/omni` — strips `/omni`, compresses bulky `tool_result` blocks, logs savings to the dashboard, and forwards to OmniRoute (`http://127.0.0.1:20128` by default, or `BACKCHANNEL_OMNIROUTE_URL`)

## CLI Commands

```bash
backchannel all [--open]                # Enable & start all 6 engines, dashboard, proxy, and graph
backchannel up [--port 4242]            # Start background daemon
backchannel ps                          # Show daemon status, PID, and proxy stats
backchannel down                        # Stop background daemon
backchannel claude [args...]            # Launch Claude through primary proxy (:4243)
backchannel claude-omni [args...]       # Launch Claude through OmniRoute proxy (:4243/omni)
backchannel mode [engine] [value]       # View or switch voice, minimalism, compression, graph, memory
backchannel graph build [dir]           # Build local codebase graph
backchannel graph query <term> [dir]    # Query dependencies for a symbol or file
backchannel audit [dir]                 # Run Ponytail repo minimalism audit
backchannel compress-doc <CLAUDE.md>    # Compress markdown instructions (keeps .bak.md backup)
backchannel wrap <command...>           # Run a command with Headroom log compression
backchannel mem list | search <q>       # Inspect or search cross-session memory
backchannel status                      # Print unified 6-in-1 status summary
backchannel doctor                      # Verify runtime, hooks, stores, and daemon
```

## Slash Commands (Claude Code)

- `/bc` — start everything at once (`/bc open`, `/bc terse`, `/bc ultra`, `/bc status`, `/bc off`)
- `/backchannel` — start/inspect the full suite
- `/backchannel-mode` — switch active engine modes
- `/backchannel-graph` — build or query the codebase graph
- `/backchannel-audit` — run minimalism audit
- `/backchannel-mem` — search or add persistent project memories
- `/backchannel-status` — view session filler ratio, token spend, and compression savings

## MCP Server

`scripts/mcp.py` (`python -m backchannel.mcp` / `backchannel-mcp`) exposes 13 tools over JSON-RPC 2.0 (memory search/save/timeline/delete/summarize, graph build/query, log compression, markdown compression, repo audit, mode configuration, chatter status, and local PDF/HTML text extraction) configured in `.mcp.json`.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT
