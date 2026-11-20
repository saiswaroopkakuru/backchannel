---
name: backchannel-audit
description: >
  Ponytail repo-wide minimalism audit: scan an entire project for replaceable
  dependencies, orphan modules, unused exports, and oversized monoliths.
  Trigger: /backchannel-audit or /ponytail-audit.
---

# backchannel-audit (Ponytail Repo Audit)

Run a deterministic minimalism scan via MCP `backchannel_repo_audit` or CLI:

```bash
backchannel audit .
```

Report the minimalism score (0-100), replaceable npm packages, orphan files, unused exports, and the top 3 highest-impact deletions or simplifications.
