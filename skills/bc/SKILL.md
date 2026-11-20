---
name: bc
description: >
  One-command activator for the entire backchannel suite (Dashboard :4242,
  Headroom Proxy :4243, OmniRoute Proxy :4243/omni -> :20128, Graphify index,
  Caveman English voice, Ponytail minimalism, Claude-Mem, and MCP).
  Use when the user types /bc or asks to run everything at once.
---

# /bc — Start Everything At Once

Run ONE command based on `$ARGUMENTS` (if empty, start everything):

- **Default (`/bc` or empty)**: run `backchannel all`
- **`open`**: run `backchannel all --open`
- **`off` / `stop` / `down`**: run `backchannel down`
- **`status` / `ps`**: run `backchannel ps`
- **`terse` / `ultra` / `mega`**: run `backchannel mode voice <arg> && backchannel all`
- **`lite` / `full`**: run `backchannel mode minimalism <arg> && backchannel all`

Execution rules:
1. Run the single shell command immediately (do not ask for confirmation).
2. If `backchannel` is not on PATH, run `python -m backchannel all` from `${CLAUDE_PLUGIN_ROOT}`.
3. Reply with a compact 5-line status summary showing:
   - Dashboard URL (`http://127.0.0.1:4242`)
   - Primary Proxy (`http://127.0.0.1:4243`)
   - OmniRoute Proxy (`http://127.0.0.1:4243/omni -> http://127.0.0.1:20128`)
   - Graphify indexed files/symbols
   - Active engines (Caveman · Ponytail · Headroom · Graphify · Claude-Mem · MCP)
4. Always reply in plain English (never Chinese).
