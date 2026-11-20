---
name: backchannel-mode
description: >
  Toggle Caveman voice (off/terse/ultra/megacave), Ponytail minimalism
  (off/lite/full/ultra), Headroom compression (off/on/aggressive), Graphify
  routing, or Claude-Mem recall. Trigger: /backchannel-mode, /caveman, /ponytail.
---

# backchannel-mode

Inspect or update `~/.backchannel/config.json`:

```bash
backchannel mode
backchannel mode voice terse        # off | terse | ultra | megacave
backchannel mode minimalism full    # off | lite | full | ultra
backchannel mode compression on     # off | on | aggressive
backchannel mode graph on           # on | off
backchannel mode memory on          # on | off
```

When switching `voice` or `minimalism`, adopt the requested mode immediately in this session too and confirm in one line.
