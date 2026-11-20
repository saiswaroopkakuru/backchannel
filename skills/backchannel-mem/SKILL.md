---
name: backchannel-mem
description: >
  Claude-Mem engine: save, search, or list persistent cross-session observations
  (decisions, bugfixes, patterns, preferences, gotchas) stored locally in
  ~/.backchannel/memories.jsonl. Trigger: /backchannel-mem or "remember this".
---

# backchannel-mem (Claude-Mem)

Manage local cross-session project memory.

```bash
# Search memories (progressive disclosure)
backchannel mem search "<query>"

# Save a concise observation
backchannel mem add "<observation>" --kind bugfix --project <name>

# List recent observations
backchannel mem list
```

Valid `--kind` values: `decision`, `bugfix`, `pattern`, `preference`, `gotcha`. Keep entries concise with `path:line` citations when relevant.
