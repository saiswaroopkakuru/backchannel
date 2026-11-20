"""Realistic built-in Claude Code multi-agent demo sessions and live SSE replay script."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any


def _iso_at(minutes_ago: int, offset_sec: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago) + timedelta(seconds=offset_sec)
    return dt.isoformat().replace("+00:00", "Z")


def get_demo_sessions() -> list[dict[str, Any]]:
    return [
        {
            "id": "sess-auth-refresh-race",
            "title": "Fix JWT refresh race under concurrent tab requests",
            "project": "ledger-api",
            "source": "demo",
            "startedAt": _iso_at(42, 0),
            "agents": [
                {"id": "lead", "name": "Lead", "role": "orchestrator", "model": "claude-sonnet-4-6", "parentId": None, "spawnDepth": 0, "status": "done", "hue": 152},
                {"id": "explorer", "name": "Explorer", "role": "researcher", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 212},
                {"id": "builder", "name": "Builder", "role": "implementer", "model": "claude-sonnet-4-6", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 34},
                {"id": "reviewer", "name": "Reviewer", "role": "code-reviewer", "model": "claude-opus-4-6", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 340},
                {"id": "verifier", "name": "Verifier", "role": "test-runner", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 186},
            ],
            "messages": [
                {"id": "ar-01", "offsetSec": 0, "timestamp": _iso_at(42, 0), "fromAgentId": "user", "toAgentId": "lead", "kind": "delegation", "text": "Users get logged out when two browser tabs refresh JWTs simultaneously. Reproduce, patch with an atomic Redis lock, review, and run the auth suite.", "inputTokens": 0, "outputTokens": 31, "cacheReadTokens": 0, "latencyMs": 0},
                {"id": "ar-02", "offsetSec": 3, "timestamp": _iso_at(42, 3), "fromAgentId": "lead", "toAgentId": "explorer", "kind": "delegation", "toolName": "Agent", "text": "Trace refresh token rotation in `src/auth/refresh.ts` and `src/auth/session-store.ts`. Return exact file:line citations for token invalidation and Redis key layout.", "inputTokens": 4820, "outputTokens": 64, "cacheReadTokens": 12400, "latencyMs": 1120},
                {"id": "ar-03", "offsetSec": 9, "timestamp": _iso_at(42, 9), "fromAgentId": "explorer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Found non-atomic read-then-rotate at `src/auth/refresh.ts:L74-L98`. Key `rt:{familyId}` is deleted at L86 before issuing new token at L94; concurrent request hits L79 and trips reuse-detection revoke (`HTTP 401` `ERR_TOKEN_REUSE`). Redis client is already exposed via `src/lib/redis.ts:L12`.", "inputTokens": 8940, "outputTokens": 142, "cacheReadTokens": 6100, "latencyMs": 2480},
                {"id": "ar-04", "offsetSec": 13, "timestamp": _iso_at(42, 13), "fromAgentId": "lead", "toAgentId": "builder", "kind": "delegation", "toolName": "Agent", "text": "Patch `src/auth/refresh.ts:L74-L98`. Guard rotation per `familyId` with `SET lock:rt:{familyId} NX PX 5000` and cache the rotated token pair for 10s so the second in-flight tab receives the same pair instead of `ERR_TOKEN_REUSE`. Add unit test in `test/auth/refresh.test.ts`.", "inputTokens": 6210, "outputTokens": 118, "cacheReadTokens": 18500, "latencyMs": 1490},
                {"id": "ar-05", "offsetSec": 25, "timestamp": _iso_at(42, 25), "fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Updated `src/auth/refresh.ts:L74-L121` with `acquireRefreshLock` and 10s grace key `rt:grace:{oldJti}`. Added `test/auth/refresh.test.ts:L88` firing `Promise.all([refresh(), refresh()])`. Please run auth test suite.", "inputTokens": 11420, "outputTokens": 214, "cacheReadTokens": 14200, "latencyMs": 4120},
                {"id": "ar-06", "offsetSec": 32, "timestamp": _iso_at(42, 32), "fromAgentId": "verifier", "toAgentId": "builder", "kind": "gate", "toolName": "SendMessage", "text": "14/15 passed in `test/auth/refresh.test.ts` (482ms). 1 fail: `revokes family on replay after grace window` timed out waiting on lock release when `rotate()` threw at L109 — missing `finally { releaseLock() }`.", "inputTokens": 5410, "outputTokens": 96, "cacheReadTokens": 4800, "latencyMs": 1840},
                {"id": "ar-07", "offsetSec": 39, "timestamp": _iso_at(42, 39), "fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Wrapped `rotate()` in `try/finally` with Lua compare-and-del lock release at `src/auth/refresh.ts:L114-L129`. Re-run `test/auth/refresh.test.ts`.", "inputTokens": 7830, "outputTokens": 112, "cacheReadTokens": 19600, "latencyMs": 2210},
                {"id": "ar-08", "offsetSec": 44, "timestamp": _iso_at(42, 44), "fromAgentId": "verifier", "toAgentId": "lead", "kind": "gate", "toolName": "TaskCompleted", "text": "`test/auth/refresh.test.ts`: 15/15 tests pass in 390ms. Concurrent tab test returns identical access token with 0 false revocations.", "inputTokens": 4620, "outputTokens": 72, "cacheReadTokens": 7900, "latencyMs": 1360},
                {"id": "ar-09", "offsetSec": 47, "timestamp": _iso_at(42, 47), "fromAgentId": "lead", "toAgentId": "reviewer", "kind": "delegation", "toolName": "Agent", "text": "Review git diff for `src/auth/refresh.ts` and `test/auth/refresh.test.ts`. Check lock safety, token leakage, and TTL edge cases.", "inputTokens": 5340, "outputTokens": 58, "cacheReadTokens": 21400, "latencyMs": 1080},
                {"id": "ar-10", "offsetSec": 59, "timestamp": _iso_at(42, 59), "fromAgentId": "reviewer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Sure! I would be happy to review this diff carefully. Let me take a look at the lock logic and basically walk through what I found. Here are my findings: in order to avoid leaking plaintext tokens in Redis, `rt:grace:{oldJti}` at `src/auth/refresh.ts:L102` should store an HMAC-encrypted payload rather than raw JSON. It seems like the 5000ms lock TTL is actually fine, and to summarize, everything else looks clean. Hope this helps, and feel free to ask if you need anything else!", "inputTokens": 9820, "outputTokens": 1180, "cacheReadTokens": 8200, "latencyMs": 5640},
                {"id": "ar-11", "offsetSec": 63, "timestamp": _iso_at(42, 63), "fromAgentId": "lead", "toAgentId": "builder", "kind": "delegation", "toolName": "SendMessage", "text": "Reviewer flagged plaintext storage in `rt:grace:{oldJti}` at `src/auth/refresh.ts:L102`. Seal the grace payload with `sealTokenPair()` from `src/auth/crypto.ts:L24` and keep the 10s TTL.", "inputTokens": 6180, "outputTokens": 82, "cacheReadTokens": 24100, "latencyMs": 1190},
                {"id": "ar-12", "offsetSec": 72, "timestamp": _iso_at(42, 72), "fromAgentId": "builder", "toAgentId": "reviewer", "kind": "peer", "toolName": "SendMessage", "text": "Sealed `rt:grace:{oldJti}` with `sealTokenPair()` (`AES-256-GCM`) at `src/auth/refresh.ts:L101-L108` and verified ciphertext format in `test/auth/refresh.test.ts:L122`.", "inputTokens": 7490, "outputTokens": 128, "cacheReadTokens": 20400, "latencyMs": 2680},
                {"id": "ar-13", "offsetSec": 81, "timestamp": _iso_at(42, 81), "fromAgentId": "reviewer", "toAgentId": "lead", "kind": "reply", "toolName": "SendMessage", "text": "Certainly! Thanks for the quick update. I have carefully reviewed the updated `AES-256-GCM` sealing at `src/auth/refresh.ts:L101-L108` and basically everything has been updated accordingly. Just wanted to note that the nonce rotation looks solid and there are no remaining security issues. Let me know if you need any further review!", "inputTokens": 8140, "outputTokens": 920, "cacheReadTokens": 11900, "latencyMs": 4210},
                {"id": "ar-14", "offsetSec": 85, "timestamp": _iso_at(42, 85), "fromAgentId": "lead", "toAgentId": "verifier", "kind": "delegation", "toolName": "SendMessage", "text": "Run full auth + session test suite (`npm test -- test/auth`) after sealing change.", "inputTokens": 4290, "outputTokens": 46, "cacheReadTokens": 26200, "latencyMs": 840},
                {"id": "ar-15", "offsetSec": 91, "timestamp": _iso_at(42, 91), "fromAgentId": "verifier", "toAgentId": "lead", "kind": "gate", "toolName": "TaskCompleted", "text": "`npm test -- test/auth`: 42/42 tests pass in 1.14s. 0 lint errors, typecheck clean.", "inputTokens": 4120, "outputTokens": 54, "cacheReadTokens": 9400, "latencyMs": 1420},
                {"id": "ar-16", "offsetSec": 95, "timestamp": _iso_at(42, 95), "fromAgentId": "lead", "toAgentId": "user", "kind": "reply", "text": "Fixed concurrent JWT refresh race in `src/auth/refresh.ts`: added atomic per-family Redis lock (`NX PX 5000`) with Lua `finally` release and 10s `AES-256-GCM` sealed grace cache. 42/42 auth tests pass.", "inputTokens": 5110, "outputTokens": 110, "cacheReadTokens": 28900, "latencyMs": 1310},
            ],
        },
        {
            "id": "sess-webhook-retry-queue",
            "title": "Add idempotent backoff queue for Stripe webhooks",
            "project": "payflow-worker",
            "source": "demo",
            "startedAt": _iso_at(135, 0),
            "agents": [
                {"id": "lead", "name": "Lead", "role": "orchestrator", "model": "claude-sonnet-4-6", "parentId": None, "spawnDepth": 0, "status": "done", "hue": 152},
                {"id": "explorer", "name": "Explorer", "role": "researcher", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 212},
                {"id": "builder", "name": "Builder", "role": "implementer", "model": "claude-sonnet-4-6", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 34},
                {"id": "verifier", "name": "Verifier", "role": "test-runner", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 186},
            ],
            "messages": [
                {"id": "wh-01", "offsetSec": 0, "timestamp": _iso_at(135, 0), "fromAgentId": "user", "toAgentId": "lead", "kind": "delegation", "text": "Stripe webhook retries duplicate invoice ledger entries when Postgres momentarily times out. Add idempotency key guard and capped exponential backoff.", "inputTokens": 0, "outputTokens": 26, "cacheReadTokens": 0, "latencyMs": 0},
                {"id": "wh-02", "offsetSec": 4, "timestamp": _iso_at(135, 4), "fromAgentId": "lead", "toAgentId": "explorer", "kind": "delegation", "toolName": "Agent", "text": "Map webhook entry point, ledger insert query, and existing retry helper in `workers/stripe-webhook.ts`.", "inputTokens": 4120, "outputTokens": 44, "cacheReadTokens": 9200, "latencyMs": 980},
                {"id": "wh-03", "offsetSec": 11, "timestamp": _iso_at(135, 11), "fromAgentId": "explorer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Handler at `workers/stripe-webhook.ts:L41`. `insertInvoiceEvent()` at `db/ledger.ts:L63` lacks `ON CONFLICT (stripe_event_id) DO NOTHING`. Existing `backoffMs()` util already lives in `lib/retry.ts:L8`.", "inputTokens": 6810, "outputTokens": 98, "cacheReadTokens": 4400, "latencyMs": 1920},
                {"id": "wh-04", "offsetSec": 16, "timestamp": _iso_at(135, 16), "fromAgentId": "lead", "toAgentId": "builder", "kind": "delegation", "toolName": "Agent", "text": "Reuse `backoffMs()` from `lib/retry.ts:L8` (max 5 attempts, 30s cap) and add `ON CONFLICT (stripe_event_id) DO NOTHING` in `db/ledger.ts:L63`. Return `HTTP 200` on duplicate delivery.", "inputTokens": 5490, "outputTokens": 86, "cacheReadTokens": 13800, "latencyMs": 1290},
                {"id": "wh-05", "offsetSec": 28, "timestamp": _iso_at(135, 28), "fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Sure, I will now hand off the patch. Updated `db/ledger.ts:L63` and `workers/stripe-webhook.ts:L48-L82` with capped backoff and duplicate `HTTP 200` handling. Let me know if you need anything else while running `test/stripe-webhook.test.ts`.", "inputTokens": 8920, "outputTokens": 184, "cacheReadTokens": 11200, "latencyMs": 3180},
                {"id": "wh-06", "offsetSec": 34, "timestamp": _iso_at(135, 34), "fromAgentId": "verifier", "toAgentId": "builder", "kind": "gate", "toolName": "SendMessage", "text": "Fail in `test/stripe-webhook.test.ts:L44`: fake timer did not advance past jittered retry delay (test expected deterministic 1000ms, got 1247ms).", "inputTokens": 4820, "outputTokens": 78, "cacheReadTokens": 5100, "latencyMs": 1510},
                {"id": "wh-07", "offsetSec": 41, "timestamp": _iso_at(135, 41), "fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Injected `jitterFn` option defaulting to `Math.random` in `workers/stripe-webhook.ts:L52` and passed `() => 0` in the unit test. Re-run.", "inputTokens": 6140, "outputTokens": 92, "cacheReadTokens": 14600, "latencyMs": 1940},
                {"id": "wh-08", "offsetSec": 46, "timestamp": _iso_at(135, 46), "fromAgentId": "verifier", "toAgentId": "builder", "kind": "gate", "toolName": "SendMessage", "text": "Second fail: `dlq.enqueue()` not called after attempt 5 because loop condition used `< 5` instead of `<= 5` at `workers/stripe-webhook.ts:L61`.", "inputTokens": 4950, "outputTokens": 74, "cacheReadTokens": 6400, "latencyMs": 1420},
                {"id": "wh-09", "offsetSec": 52, "timestamp": _iso_at(135, 52), "fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Changed retry bound to `attempt <= maxAttempts` at `workers/stripe-webhook.ts:L61` and verified DLQ handoff assertion.", "inputTokens": 5830, "outputTokens": 76, "cacheReadTokens": 15900, "latencyMs": 1620},
                {"id": "wh-10", "offsetSec": 57, "timestamp": _iso_at(135, 57), "fromAgentId": "verifier", "toAgentId": "lead", "kind": "gate", "toolName": "TaskCompleted", "text": "`test/stripe-webhook.test.ts`: 19/19 tests pass in 310ms. Duplicate event IDs return `HTTP 200` with 0 duplicate rows.", "inputTokens": 4210, "outputTokens": 62, "cacheReadTokens": 7200, "latencyMs": 1180},
                {"id": "wh-11", "offsetSec": 61, "timestamp": _iso_at(135, 61), "fromAgentId": "lead", "toAgentId": "user", "kind": "reply", "text": "Added idempotent `ON CONFLICT (stripe_event_id) DO NOTHING` in `db/ledger.ts:L63` and capped exponential backoff + DLQ handoff in `workers/stripe-webhook.ts`. 19/19 tests pass.", "inputTokens": 4860, "outputTokens": 96, "cacheReadTokens": 18400, "latencyMs": 1140},
            ],
        },
        {
            "id": "sess-sql-n-plus-one",
            "title": "Eliminate N+1 inventory queries on storefront catalog",
            "project": "catalog-service",
            "source": "demo",
            "startedAt": _iso_at(260, 0),
            "agents": [
                {"id": "lead", "name": "Lead", "role": "orchestrator", "model": "claude-sonnet-4-6", "parentId": None, "spawnDepth": 0, "status": "done", "hue": 152},
                {"id": "explorer", "name": "Explorer", "role": "researcher", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 212},
                {"id": "builder", "name": "Builder", "role": "implementer", "model": "claude-sonnet-4-6", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 34},
                {"id": "reviewer", "name": "Reviewer", "role": "code-reviewer", "model": "claude-opus-4-6", "parentId": "lead", "spawnDepth": 1, "status": "done", "hue": 340},
            ],
            "messages": [
                {"id": "sq-01", "offsetSec": 0, "timestamp": _iso_at(260, 0), "fromAgentId": "user", "toAgentId": "lead", "kind": "delegation", "text": "`GET /v1/catalog` p95 jumped from 42ms to 310ms. Find the query regression and fix it cleanly.", "inputTokens": 0, "outputTokens": 20, "cacheReadTokens": 0, "latencyMs": 0},
                {"id": "sq-02", "offsetSec": 3, "timestamp": _iso_at(260, 3), "fromAgentId": "lead", "toAgentId": "explorer", "kind": "delegation", "toolName": "Agent", "text": "Inspect `routes/catalog.ts` and `queries/inventory.sql` for per-item DB loops.", "inputTokens": 3820, "outputTokens": 36, "cacheReadTokens": 8400, "latencyMs": 880},
                {"id": "sq-03", "offsetSec": 9, "timestamp": _iso_at(260, 9), "fromAgentId": "explorer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "`routes/catalog.ts:L58` calls `getWarehouseStock(sku)` inside `Promise.all(skus.map(...))` — 42 queries per page. Composite index `(sku, updated_at DESC)` already exists in `migrations/014_stock.sql:L9`.", "inputTokens": 6120, "outputTokens": 104, "cacheReadTokens": 3900, "latencyMs": 1740},
                {"id": "sq-04", "offsetSec": 14, "timestamp": _iso_at(260, 14), "fromAgentId": "lead", "toAgentId": "builder", "kind": "delegation", "toolName": "Agent", "text": "Replace per-SKU query loop in `routes/catalog.ts:L58` with a single `ANY($1::text[])` `DISTINCT ON (sku)` query in `queries/inventory.sql`. Verify EXPLAIN uses `idx_stock_sku_updated`.", "inputTokens": 4910, "outputTokens": 78, "cacheReadTokens": 12100, "latencyMs": 1120},
                {"id": "sq-05", "offsetSec": 26, "timestamp": _iso_at(260, 26), "fromAgentId": "builder", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Added `getBatchWarehouseStock(skus)` in `queries/inventory.sql:L18-L27` and wired `routes/catalog.ts:L55-L64`. EXPLAIN confirms Index Scan on `idx_stock_sku_updated`; local p95 dropped from 310ms to 29ms (1 query vs 42).", "inputTokens": 7640, "outputTokens": 148, "cacheReadTokens": 13500, "latencyMs": 2890},
                {"id": "sq-06", "offsetSec": 31, "timestamp": _iso_at(260, 31), "fromAgentId": "lead", "toAgentId": "reviewer", "kind": "delegation", "toolName": "Agent", "text": "Check SQL parameter safety and empty-array edge case in `queries/inventory.sql:L18-L27` and `routes/catalog.ts:L55-L64`.", "inputTokens": 4510, "outputTokens": 48, "cacheReadTokens": 14900, "latencyMs": 920},
                {"id": "sq-07", "offsetSec": 41, "timestamp": _iso_at(260, 41), "fromAgentId": "reviewer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Absolutely! Here is what I found after reviewing `queries/inventory.sql:L18-L27`: basically the parameterized `ANY($1::text[])` binding is safe against injection, and empty `skus` returns an early `{}` map at `routes/catalog.ts:L56`. Overall everything looks ready to merge — hope this helps!", "inputTokens": 6940, "outputTokens": 490, "cacheReadTokens": 9100, "latencyMs": 3140},
                {"id": "sq-08", "offsetSec": 45, "timestamp": _iso_at(260, 45), "fromAgentId": "lead", "toAgentId": "user", "kind": "reply", "text": "Eliminated 42-query N+1 loop in `routes/catalog.ts:L58` using batched `DISTINCT ON (sku)` in `queries/inventory.sql`. Local p95 dropped from 310ms to 29ms.", "inputTokens": 4230, "outputTokens": 78, "cacheReadTokens": 16200, "latencyMs": 1020},
            ],
        },
    ]


def create_live_simulation_script() -> dict[str, Any]:
    return {
        "id": f"sess-live-{format(int(time.time() * 1000), 'x')}",
        "title": "Live swarm: Rate-limiter sliding window migration",
        "project": "edge-gateway",
        "source": "demo",
        "isLive": True,
        "startedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "agents": [
            {"id": "lead", "name": "Lead", "role": "orchestrator", "model": "claude-sonnet-4-6", "parentId": None, "spawnDepth": 0, "status": "speaking", "hue": 152},
            {"id": "explorer", "name": "Explorer", "role": "researcher", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "waiting", "hue": 212},
            {"id": "builder", "name": "Builder", "role": "implementer", "model": "claude-sonnet-4-6", "parentId": "lead", "spawnDepth": 1, "status": "waiting", "hue": 34},
            {"id": "reviewer", "name": "Reviewer", "role": "code-reviewer", "model": "claude-opus-4-6", "parentId": "lead", "spawnDepth": 1, "status": "waiting", "hue": 340},
            {"id": "verifier", "name": "Verifier", "role": "test-runner", "model": "claude-haiku-4-5", "parentId": "lead", "spawnDepth": 1, "status": "waiting", "hue": 186},
        ],
        "steps": [
            {"fromAgentId": "user", "toAgentId": "lead", "kind": "delegation", "text": "Replace fixed-window rate limiter in `middleware/rate-limit.ts` with a Redis sorted-set sliding window so boundary bursts cannot double our limit.", "inputTokens": 0, "outputTokens": 28, "cacheReadTokens": 0, "latencyMs": 0},
            {"fromAgentId": "lead", "toAgentId": "explorer", "kind": "delegation", "toolName": "Agent", "text": "Inspect `middleware/rate-limit.ts` and `config/limits.ts`. Report key prefix, Lua script loader, and test fixture setup.", "inputTokens": 4320, "outputTokens": 52, "cacheReadTokens": 10800, "latencyMs": 960},
            {"fromAgentId": "explorer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "`middleware/rate-limit.ts:L22-L54` uses `INCR rl:{tenant}:{minute}` with 60s `EXPIRE`. Lua loader exists at `lib/redis-scripts.ts:L15`. Fake Redis harness is in `test/helpers/redis.ts:L8`.", "inputTokens": 7180, "outputTokens": 118, "cacheReadTokens": 4900, "latencyMs": 1890},
            {"fromAgentId": "lead", "toAgentId": "all", "kind": "broadcast", "toolName": "TaskCreate", "text": "Plan locked: Builder writes atomic ZSET Lua script in `lib/lua/sliding-window.lua` + wires `middleware/rate-limit.ts`; Verifier tests boundary bursts; Reviewer audits atomicity.", "inputTokens": 5120, "outputTokens": 74, "cacheReadTokens": 14200, "latencyMs": 1040},
            {"fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Added `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` Lua script at `lib/lua/sliding-window.lua:L1-L18` and updated `middleware/rate-limit.ts:L26-L49`. Ready for burst tests.", "inputTokens": 9340, "outputTokens": 176, "cacheReadTokens": 12800, "latencyMs": 3120},
            {"fromAgentId": "verifier", "toAgentId": "builder", "kind": "gate", "toolName": "SendMessage", "text": "8/9 tests pass in `test/rate-limit.test.ts` (240ms). 1 fail: same-millisecond requests collided on ZSET member `${now}` — append unique request UUID to member key.", "inputTokens": 4920, "outputTokens": 86, "cacheReadTokens": 5200, "latencyMs": 1490},
            {"fromAgentId": "builder", "toAgentId": "verifier", "kind": "peer", "toolName": "SendMessage", "text": "Changed ZSET member to `${now}:${crypto.randomUUID()}` at `lib/lua/sliding-window.lua:L11`. Re-run burst test.", "inputTokens": 6180, "outputTokens": 72, "cacheReadTokens": 16400, "latencyMs": 1710},
            {"fromAgentId": "verifier", "toAgentId": "lead", "kind": "gate", "toolName": "TaskCompleted", "text": "9/9 tests pass in 215ms including 100-req simultaneous millisecond boundary burst (`HTTP 429` triggers cleanly on req #101).", "inputTokens": 4410, "outputTokens": 68, "cacheReadTokens": 7800, "latencyMs": 1210},
            {"fromAgentId": "reviewer", "toAgentId": "lead", "kind": "reply", "toolName": "Agent", "text": "Sure! I would be happy to review this migration. Let me take a look at `lib/lua/sliding-window.lua:L1-L18`. Basically the `PEXPIRE` call prevents stale keys from accumulating, and it seems like the unique member ID resolves the collision cleanly. To summarize, everything looks production-ready — hope this helps!", "inputTokens": 7890, "outputTokens": 760, "cacheReadTokens": 9600, "latencyMs": 3820},
            {"fromAgentId": "lead", "toAgentId": "user", "kind": "reply", "text": "Migrated `middleware/rate-limit.ts` to atomic Redis ZSET sliding window (`lib/lua/sliding-window.lua`). Eliminated boundary burst doubling; 9/9 tests pass.", "inputTokens": 4820, "outputTokens": 88, "cacheReadTokens": 19200, "latencyMs": 1120},
        ],
    }
