---
name: backchannel
description: >
  Start or inspect the unified 6-in-1 backchannel background suite (Dashboard +
  Headroom API Proxy + OmniRoute Proxy + Graphify + Caveman + Ponytail + Claude-Mem + MCP).
  Use for /backchannel, /bc, "start backchannel", or "open dashboard".
---

# backchannel (v3.0.0)

Start EVERY engine in the background with one command:

```bash
# Enable all 6 engines + start Dashboard (:4242) + Primary Proxy (:4243) + OmniRoute (:4243/omni) + Graphify
backchannel all

# Or run directly with Python:
python -m backchannel all
```

Useful controls:
- `backchannel all --open` — start everything and open the dashboard in browser
- `backchannel ps` — check running daemon PID, primary proxy & OmniRoute stats
- `backchannel down` — stop the background daemon
- `backchannel claude` / `backchannel claude-omni` — launch Claude wired through Backchannel (primary or OmniRoute)
- `backchannel status` — unified 6-in-1 summary

Report the dashboard URL (`http://127.0.0.1:4242`), primary proxy (`http://127.0.0.1:4243`), OmniRoute proxy (`http://127.0.0.1:4243/omni`), active engines, and Graphify index concisely in plain English.
