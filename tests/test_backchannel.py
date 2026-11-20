"""Comprehensive unittest suite for the 6-in-1 Python backchannel plugin & MCP server."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from backchannel.analyzer import analyze_message_text, analyze_session
from backchannel.compressor import compress_tool_output, load_savings_ledger
from backchannel.config import (
    DEFAULT_CONFIG,
    detect_claude_upstream_url,
    resolve_omniroute_upstream,
    resolve_proxy_upstream,
    save_config,
)
from backchannel.daemon import get_daemon_status, start_background_daemon, stop_background_daemon
from backchannel.demo_data import get_demo_sessions
from backchannel.doc_compress import compress_markdown_file
from backchannel.graphify import build_knowledge_graph, extract_pdf_facts, query_knowledge_graph
from backchannel.hook import build_graphify_search_hint, normalize_hook_payload
from backchannel.mcp import MCP_TOOLS, handle_jsonrpc_message
from backchannel.memory import add_memory, delete_memory, search_memories, summarize_session_to_memory
from backchannel.modes import build_policy_prompt
from backchannel.proxy import HeadroomProxyServer
from backchannel.repo_audit import run_repo_audit
from backchannel.server import DashboardServer
from backchannel.store import (
    BackchannelStore,
    build_sessions_from_hook_events,
    is_hex_or_machine_id,
    parse_claude_transcript_file,
    prettify_agent_name,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _http_json(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = Request(url, data=data, headers=hdrs, method=method)
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestAnalyzerAndStore(unittest.TestCase):
    def test_analyze_message_text_filler_vs_payload(self) -> None:
        chatty = analyze_message_text(
            "Sure! I would be happy to help. Basically let me take a look and hope this helps, feel free to ask!"
        )
        terse = analyze_message_text(
            "Patched `src/auth/refresh.ts:L74-L98` with Redis lock. 15/15 tests pass in 390ms."
        )
        self.assertGreater(chatty["fillerPct"], 35.0)
        self.assertEqual(terse["fillerPct"], 0.0)
        self.assertGreater(terse["payloadHits"], 0)

    def test_analyze_ignores_fenced_code_blocks(self) -> None:
        msg = "Fix applied:\n```python\n# Sure! Basically hope this helps\nprint('ok')\n```"
        res = analyze_message_text(msg)
        self.assertEqual(res["fillerPct"], 0.0)

    def test_demo_sessions_reconcile_totals(self) -> None:
        for raw in get_demo_sessions():
            analyzed = analyze_session(raw)
            sum_out = sum(a["outputTokens"] for a in analyzed["agents"])
            sum_cost = round(sum(a["costUsd"] for a in analyzed["agents"]), 2)
            self.assertEqual(analyzed["summary"]["totalOutputTokens"], sum_out)
            self.assertEqual(analyzed["summary"]["totalCostUsd"], sum_cost)

    def test_semantic_agent_naming_never_shows_raw_hex(self) -> None:
        self.assertTrue(is_hex_or_machine_id("a8da3e1e1f"))
        name1 = prettify_agent_name("a8da3e1e1f", {}, "Goal is getting your Claude setup working through backchannel")
        self.assertEqual(name1, "Setup Verifier")
        name2 = prettify_agent_name("aa165560cc", {}, "The watchdog now catches hangs on OmniRoute")
        self.assertEqual(name2, "OmniRoute Specialist")
        name3 = prettify_agent_name("deadbeef99", {}, "", 2)
        self.assertEqual(name3, "Worker 2")

    def test_transcript_parser_and_hook_store(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-store-"))
        try:
            sess_file = tmp / "abcd12345678.jsonl"
            rows = [
                {"type": "user", "timestamp": "2026-11-20T10:00:00Z", "message": {"role": "user", "content": "Check auth tests"}},
                {
                    "type": "assistant",
                    "timestamp": "2026-11-20T10:00:05Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-6",
                        "content": [{"type": "text", "text": "All 12 auth tests pass."}],
                        "usage": {"input_tokens": 500, "output_tokens": 40},
                    },
                },
            ]
            sess_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            parsed = parse_claude_transcript_file(sess_file, "my-app")
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed["project"], "my-app")
            self.assertEqual(len(parsed["messages"]), 2)

            ev = normalize_hook_payload(
                "SubagentStop",
                {
                    "session_id": "s-1",
                    "agent_id": "a4726fd7fd",
                    "cwd": "/tmp/demo",
                    "last_assistant_message": "Port 20128 is listening on localhost.",
                },
            )
            store = BackchannelStore(data_dir=tmp, claude_projects_dir=tmp / "none")
            store.record_hook_event(ev)
            built = build_sessions_from_hook_events(store.live_hook_events)
            self.assertEqual(len(built), 1)
            sub = [a for a in built[0]["agents"] if a["id"] != "lead"][0]
            self.assertEqual(sub["name"], "Port Inspector")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEngines(unittest.TestCase):
    def test_modes_english_only_no_chinese(self) -> None:
        for voice in ("terse", "ultra", "megacave"):
            pol = build_policy_prompt(
                {"voice": voice, "minimalism": "ultra", "compression": "aggressive", "graphAssist": True, "memoryAssist": False},
                preview=True,
            )
            self.assertIn(f"[Voice: {voice}]", pol["text"])
            self.assertNotIn("文言文", pol["text"])
            self.assertNotIn("Chinese", pol["text"])
        mega = build_policy_prompt({"voice": "megacave", "minimalism": "off", "compression": "off", "graphAssist": False, "memoryAssist": False})
        self.assertIn("telegraphic English", mega["text"])

    def test_headroom_compressor_preserves_errors(self) -> None:
        lines = [f"PASS test/suite_{i}.py (8ms)" for i in range(45)]
        lines.insert(20, "AssertionError: expected 200 received 500 at api/auth.py:42")
        res = compress_tool_output("\n".join(lines), mode="on")
        self.assertGreater(res["savedTokens"], 50)
        self.assertIn("AssertionError: expected 200 received 500", res["text"])
        self.assertIn("collapse-passing-tests", res["rulesApplied"])

    def test_caveman_doc_compressor_backup(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-doc-"))
        try:
            md = tmp / "CLAUDE.md"
            md.write_text(
                "# Rules\n\nPlease make sure that you basically always utilize `pytest` in order to verify changes prior to committing.\n"
                "It is important to note that you must NEVER drop production tables.\n\n"
                "```bash\n# Please make sure this code block stays untouched\npytest\n```\n",
                encoding="utf-8",
            )
            res = compress_markdown_file(md, write=True)
            self.assertGreater(res["savedTokens"], 0)
            self.assertIsNotNone(res["backupPath"])
            self.assertTrue(Path(res["backupPath"]).exists())
            self.assertIn("NEVER drop production tables", res["text"])
            self.assertIn("# Please make sure this code block stays untouched", res["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_graphify_pdf_and_pretooluse_hint(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-graph-"))
        try:
            stream = zlib.compress(b"BT (Architecture Overview) Tj [(Graphify ) (Engine)] TJ ET")
            pdf_bytes = b"%PDF-1.4\n/Title (System Spec)\nstream\n" + stream + b"\nendstream\n%%EOF"
            facts = extract_pdf_facts(pdf_bytes)
            self.assertIn("System Spec", facts["text"])
            self.assertIn("Architecture Overview", facts["symbols"])

            (tmp / "spec.pdf").write_bytes(pdf_bytes)
            (tmp / "app.py").write_text("from util import helper\ndef main():\n    return helper()\n", encoding="utf-8")
            (tmp / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
            graph = build_knowledge_graph(tmp, persist=True)
            self.assertEqual(graph["stats"]["pdfCount"], 1)
            self.assertGreaterEqual(graph["stats"]["edgeCount"], 1)

            q = query_knowledge_graph(graph, "helper")
            self.assertTrue(any(m["id"] == "util.py" for m in q["matches"]))

            hint = build_graphify_search_hint({"cwd": str(tmp), "tool_input": {"pattern": "helper"}}, {"graphAssist": True})
            self.assertIsNotNone(hint)
            assert hint is not None
            self.assertIn("util.py", hint)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_memory_hybrid_search_summarize_and_delete(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-mem-"))
        try:
            m1 = add_memory({"title": "Redis lock fix", "body": "Guarded JWT refresh in auth.py with NX lock", "project": "api", "kind": "bugfix", "tags": ["redis", "jwt"]}, tmp)
            m1_dup = add_memory({"title": "Redis lock fix", "body": "Guarded JWT refresh in auth.py with NX lock", "project": "api", "kind": "bugfix"}, tmp)
            self.assertEqual(m1["id"], m1_dup["id"])

            hits = search_memories(query="JWT refresh lock", project="api", override_dir=tmp)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["id"], m1["id"])

            sess = analyze_session(get_demo_sessions()[0])
            summ = summarize_session_to_memory(sess, tmp)
            self.assertIsNotNone(summ)
            self.assertTrue(delete_memory(m1["id"], tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ponytail_repo_audit(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-audit-"))
        try:
            (tmp / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.21", "moment": "^2.30.0"}}), encoding="utf-8")
            (tmp / "orphan_helper.py").write_text("def unused_thing():\n    return 1\n", encoding="utf-8")
            audit = run_repo_audit(tmp)
            cats = {f["category"] for f in audit["findings"]}
            self.assertIn("redundant-dep", cats)
            self.assertIn("orphan-module", cats)
            self.assertLess(audit["score"], 100)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestProxyAndOmniRoute(unittest.TestCase):
    def _make_mock_upstream(self, tag: str) -> tuple[HTTPServer, threading.Thread, int]:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                cl = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(cl) if cl > 0 else b""
                payload = json.dumps({"server": tag, "path": self.path, "bytes": len(raw), "body": json.loads(raw.decode("utf-8")) if raw else None}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                payload = json.dumps({"server": tag, "path": self.path}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, t, port

    def test_proxy_compression_upstream_chaining_and_omniroute(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-px-"))
        primary_srv, _, p_port = self._make_mock_upstream("primary")
        omni_srv, _, o_port = self._make_mock_upstream("omniroute")

        # Verify Claude & OmniRoute upstream auto-detection + loop prevention
        c_file = tmp / "settings.json"
        c_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{p_port}/w/claude"}}), encoding="utf-8")
        self.assertEqual(detect_claude_upstream_url(4243, c_file), f"http://127.0.0.1:{p_port}/w/claude")
        self.assertEqual(resolve_proxy_upstream(DEFAULT_CONFIG, proxy_port=4243, claude_settings_path=c_file), f"http://127.0.0.1:{p_port}/w/claude")

        loop_file = tmp / "loop.json"
        loop_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4243"}}), encoding="utf-8")
        self.assertIsNone(detect_claude_upstream_url(4243, loop_file))

        o_file = tmp / "omni.json"
        o_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{o_port}"}}), encoding="utf-8")
        self.assertEqual(resolve_omniroute_upstream(DEFAULT_CONFIG, proxy_port=4243, omni_settings_path=o_file), f"http://127.0.0.1:{o_port}")

        proxy = HeadroomProxyServer(
            port=0,
            upstream=f"http://127.0.0.1:{p_port}/w/claude",
            omni_upstream=f"http://127.0.0.1:{o_port}",
            data_dir=tmp,
            mode="on",
        )
        px_port = proxy.start()

        try:
            noisy = "\n".join(f"PASS test/s-{i}.py (7ms)" for i in range(45)) + "\nAssertionError: keep this error"
            cached_text = "x" * 1800
            req_body = {
                "model": "claude-sonnet-4-6",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "tu_1", "content": noisy},
                            {"type": "tool_result", "tool_use_id": "tu_cached", "cache_control": {"type": "ephemeral"}, "content": cached_text},
                        ],
                    }
                ],
            }
            orig_size = len(json.dumps(req_body).encode("utf-8"))

            # 1. Primary route chains /w/claude, compresses uncached block, preserves cache_control & error
            status, r1 = _http_json(f"http://127.0.0.1:{px_port}/v1/messages?beta=true", "POST", req_body)
            self.assertEqual(status, 200)
            self.assertEqual(r1["server"], "primary")
            self.assertEqual(r1["path"], "/w/claude/v1/messages?beta=true")
            self.assertLess(r1["bytes"], orig_size)
            sent_blocks = r1["body"]["messages"][0]["content"]
            self.assertIn("AssertionError: keep this error", sent_blocks[0]["content"])
            self.assertEqual(len(sent_blocks[1]["content"]), 1800)

            # 2. count_tokens passes untouched
            status2, r2 = _http_json(f"http://127.0.0.1:{px_port}/v1/messages/count_tokens", "POST", req_body)
            self.assertEqual(status2, 200)
            self.assertEqual(r2["path"], "/w/claude/v1/messages/count_tokens")
            self.assertEqual(r2["bytes"], orig_size)

            # 3. OmniRoute /omni/v1/messages strips /omni, compresses, forwards to OmniRoute
            status3, r3 = _http_json(f"http://127.0.0.1:{px_port}/omni/v1/messages?beta=true", "POST", req_body)
            self.assertEqual(status3, 200)
            self.assertEqual(r3["server"], "omniroute")
            self.assertEqual(r3["path"], "/v1/messages?beta=true")
            self.assertLess(r3["bytes"], orig_size)

            # 4. Health & savings ledger
            _, health = _http_json(f"http://127.0.0.1:{px_port}/_backchannel/health")
            self.assertTrue(health["ok"])
            self.assertEqual(health["omniUpstream"], f"http://127.0.0.1:{o_port}")
            self.assertEqual(health["omniRequestsProxied"], 1)
            self.assertEqual(health["omniRequestsCompressed"], 1)

            ledger = load_savings_ledger(tmp)
            sources = {e["source"] for e in ledger}
            self.assertIn("proxy:/v1/messages", sources)
            self.assertIn("proxy:omni:/v1/messages", sources)
        finally:
            proxy.stop()
            primary_srv.shutdown()
            primary_srv.server_close()
            omni_srv.shutdown()
            omni_srv.server_close()
            shutil.rmtree(tmp, ignore_errors=True)


class TestServerMcpAndDaemon(unittest.TestCase):
    def test_dashboard_server_endpoints(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-srv-"))
        dash = DashboardServer(demo=True, data_dir=tmp, graph_dir=REPO_ROOT)
        port = dash.start(port=0)
        try:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
                html = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
                self.assertIn("backchannel", html)

            status, state = _http_json(f"http://127.0.0.1:{port}/api/state?mode=demo")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(state["sessions"]), 3)
            self.assertIn("omniUrl", state["proxy"])

            status, cfg_res = _http_json(f"http://127.0.0.1:{port}/api/config", "POST", {"voice": "ultra"})
            self.assertEqual(status, 200)
            self.assertEqual(cfg_res["config"]["voice"], "ultra")

            status, mem_res = _http_json(f"http://127.0.0.1:{port}/api/memories", "POST", {"title": "Test note", "body": "Body detail", "project": "test"})
            self.assertEqual(status, 201)
            mem_id = mem_res["entry"]["id"]

            status, del_res = _http_json(f"http://127.0.0.1:{port}/api/memories/{mem_id}", "DELETE")
            self.assertEqual(status, 200)
            self.assertTrue(del_res["ok"])

            with urlopen(f"http://127.0.0.1:{port}/api/card.svg?mode=demo&scope=portfolio", timeout=5) as resp:
                svg = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
                self.assertIn("<svg", svg)
        finally:
            dash.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_mcp_jsonrpc_13_tools(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-mcp-"))
        try:
            init = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, data_dir=tmp, cwd=REPO_ROOT)
            self.assertEqual(init["result"]["serverInfo"]["name"], "backchannel")

            listed = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, data_dir=tmp, cwd=REPO_ROOT)
            self.assertEqual(len(listed["result"]["tools"]), 13)
            self.assertEqual(len(MCP_TOOLS), 13)

            saved = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "backchannel_memory_save", "arguments": {"title": "MCP test", "body": "Saved via Python MCP", "project": "demo"}},
                },
                data_dir=tmp,
                cwd=REPO_ROOT,
            )
            payload = json.loads(saved["result"]["content"][0]["text"])
            self.assertTrue(payload["saved"])

            mode_res = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "backchannel_mode", "arguments": {"voice": "terse"}},
                },
                data_dir=tmp,
                cwd=REPO_ROOT,
            )
            mode_payload = json.loads(mode_res["result"]["content"][0]["text"])
            self.assertEqual(mode_payload["config"]["voice"], "terse")
            self.assertNotIn("文言文", mode_payload["policy"]["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_background_daemon_lifecycle(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bc-daemon-"))
        try:
            info = start_background_daemon(
                port=14242,
                proxy_port=14243,
                upstream="http://127.0.0.1:19999",
                omni_upstream="http://127.0.0.1:20128",
                graph_dir=REPO_ROOT,
                data_dir=tmp,
                demo=True,
            )
            self.assertTrue(info["running"])
            self.assertTrue(info["dashboardUp"])
            self.assertTrue(info["proxyUp"])
            self.assertEqual(info["omniUpstream"], "http://127.0.0.1:20128")

            st = get_daemon_status(tmp)
            self.assertTrue(st["running"])
            self.assertEqual(st["dashboardPort"], 14242)
            self.assertEqual(st["proxyPort"], 14243)

            stopped = stop_background_daemon(tmp)
            self.assertTrue(stopped["stopped"])
        finally:
            stop_background_daemon(tmp)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
