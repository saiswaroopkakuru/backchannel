---
name: backchannel-commit
description: >
  Caveman-style Conventional Commits message compressed to intent only (<= 50
  char subject). Trigger: /backchannel-commit or "write commit message".
---

# backchannel-commit (Caveman)

Inspect `git diff --staged` (or working tree) and produce a Conventional Commits message:

- Format: `<type>(<scope>): <imperative intent>` (`<= 50` chars)
- Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`
- Body: only when a non-obvious "why" or breaking change exists (max 2 short bullets)
- No filler, no recap of file names already in the diff.
