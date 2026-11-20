---
name: backchannel-graph
description: >
  Graphify engine: build or query a local deterministic codebase knowledge graph
  (.backchannel/graph.json) to map dependencies, hubs, and symbols without
  brute-force file scanning. Trigger: /backchannel-graph or /graphify.
---

# backchannel-graph (Graphify)

Build or query the local zero-vector codebase knowledge graph before scanning raw files.

```bash
# Build or refresh graph for current directory
backchannel graph build .

# Query matching files, symbols, and 1-hop import neighbors
backchannel graph query "<symbol-or-topic>" .
```

Use the returned hub files, exported symbols, and 1-hop callers/callees to open only the exact files needed.
