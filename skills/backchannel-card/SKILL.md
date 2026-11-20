---
name: backchannel-card
description: >
  Generate a Ponytail-style dark shareable SVG stats card summarizing multi-agent
  talk time, messages, signal ratio, tokens, and cost measured in Claude Code.
  Trigger: /backchannel-card or "export backchannel card".
---

# backchannel-card

Generate a shareable dark telemetry card from local Claude Code sessions:

```bash
backchannel card --out ./backchannel-card.svg
```

Optional flags:
- `--session <id>` — render a single session instead of all recent sessions
- `--demo` — render using the built-in multi-agent sample sessions
- `--out <path>` — output path (default `./backchannel-card.svg`)

Confirm the generated file path and list the headline metrics rendered on the card.
