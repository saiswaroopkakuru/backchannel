---
name: backchannel-compress
description: >
  Caveman markdown/CLAUDE.md compressor & Headroom in-flight proxy launcher.
  Compresses verbose .md context files with automatic .bak.md backup, or starts
  the transparent API proxy. Trigger: /backchannel-compress or /headroom.
---

# backchannel-compress (Caveman Doc + Headroom Proxy)

Compress a bulky markdown memory/context file (`CLAUDE.md`, docs, specs) keeping all code blocks, tables, paths, and negations exact (auto-creates `.bak.md`):

```bash
backchannel compress-doc CLAUDE.md
```

Or launch Claude Code through the local Headroom in-flight input compression proxy:

```bash
backchannel claude
```
