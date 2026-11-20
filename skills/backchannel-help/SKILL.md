---
name: backchannel-help
description: >
  Quick-reference card for the complete 6-in-1 backchannel v3.0.0 plugin
  (Backchannel, Caveman, Ponytail, Headroom Proxy, Graphify, Claude-Mem, MCP).
  Trigger: /backchannel-help.
---

# backchannel v3.0.0 — Complete 6-in-1 Quick Reference

| Engine | Slash command | CLI / MCP | Purpose |
|---|---|---|---|
| **Backchannel** | `/backchannel` `/backchannel-status` | `backchannel dashboard` / MCP `backchannel_chatter_status` | Multi-agent talk topology, transcript, chatter audit |
| **Caveman** | `/backchannel-mode` `/backchannel-commit` `/backchannel-compress` | `backchannel mode voice terse\|ultra\|megacave`, `compress-doc` | Output compression, Wenyan mode, `CLAUDE.md` compressor |
| **Ponytail** | `/backchannel-review` `/backchannel-audit` `/backchannel-card` | `backchannel audit .`, MCP `backchannel_repo_audit` | 7-step YAGNI ladder, repo-wide dead-code audit, share card |
| **Headroom** | `/backchannel-compress` | `backchannel claude` / `proxy` / `wrap <cmd>` | In-flight API compression proxy (`:4243`) + 5h/7d budgets |
| **Graphify** | `/backchannel-graph` | `backchannel graph build .`, MCP `backchannel_graph_query` | 16-lang + PDF local graph, PageRank hubs, Grep/Glob routing |
| **Claude-Mem** | `/backchannel-mem` | `backchannel mem`, MCP `backchannel_memory_search\|save` | Hybrid BM25+semantic memory, `SessionStart` recall, auto summaries |
