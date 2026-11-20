---
name: backchannel-review
description: >
  Combined Caveman + Ponytail diff review: one-line terse findings flagging
  bugs, security risks, over-engineering, and code that did not need to exist.
  Trigger: /backchannel-review or "review this diff".
---

# backchannel-review (Caveman + Ponytail)

Inspect `git diff` (or staged changes) and emit one line per finding:

```text
path/file.ts:L42: [bug|yagni|security|dead-code] <problem>. <minimal fix>.
```

Check both:
1. **Correctness & safety**: null guards, error handling, race conditions, trust boundaries.
2. **Ponytail minimalism ladder**: unnecessary abstractions, reinvented stdlib/platform features, unused dependencies, dead code.

Omit greetings, praise, and recaps. If clean, output `Diff clean: 0 findings.`
