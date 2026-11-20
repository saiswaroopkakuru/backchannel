---
name: backchannel-status
description: >
  Print a concise terminal audit of how Claude Code agents talked in recent
  sessions: message counts, top talker, signal ratio, filler phrases, and
  chatter tax. Trigger: /backchannel-status or "agent chatter status".
---

# backchannel-status

Run a read-only audit of recorded Claude Code multi-agent transcripts and hook events.

```bash
backchannel status --json
```

Present the summary cleanly:
- Active source (`live` transcripts/hooks or `demo` fallback)
- Sessions and total inter-agent messages
- Signal ratio (%) and chatter tax ($)
- Top talker (agent name, turn count, filler %, and top repeated ceremony phrase if any)
- One concrete prompt/delegation tightening recommendation when filler exceeds 15%.
