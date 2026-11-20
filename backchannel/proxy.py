"""Transparent Headroom + OmniRoute streaming HTTP/HTTPS compression proxy for Claude Code."""

from __future__ import annotations

import http.client
import json
import math
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .analyzer import estimate_tokens, iso_now
from .compressor import compress_tool_output, record_compression_saving
from .config import load_config, resolve_omniroute_upstream, resolve_proxy_upstream


def _slim_json_payload(text: str, mode: str) -> str | None:
    trimmed = text.strip()
    if not (trimmed.startswith("{") or trimmed.startswith("[")) or len(trimmed) < 1500:
        return None
    try:
        parsed = json.loads(trimmed)
    except Exception:
        return None

    max_items = 12 if mode == "aggressive" else 25

    def shrink(val: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[nested]"
        if isinstance(val, list):
            if len(val) > max_items:
                head_n = math.ceil(max_items / 2)
                tail_n = math.floor(max_items / 2)
                head = [shrink(v, depth + 1) for v in val[:head_n]]
                tail = [shrink(v, depth + 1) for v in val[len(val) - tail_n :]]
                omitted = len(val) - len(head) - len(tail)
                return [*head, f"... ({omitted} array items omitted by headroom proxy)", *tail]
            return [shrink(v, depth + 1) for v in val]
        if isinstance(val, dict):
            keys = list(val.keys())
            out = {k: shrink(val[k], depth + 1) for k in keys[:40]}
            if len(keys) > 40:
                out["_omittedKeys"] = len(keys) - 40
            return out
        if isinstance(val, str) and len(val) > 500:
            return f"{val[:260]} ... ({len(val) - 360} chars omitted) ... {val[-100:]}"
        return val

    compact = json.dumps(shrink(parsed), separators=(",", ":"))
    return compact if len(compact) < len(trimmed) * 0.88 else None


def compress_anthropic_messages_body(
    body_obj: dict[str, Any] | None, *, mode: str = "on", min_chars: int | None = None
) -> dict[str, Any]:
    """Compress bulky tool_result blocks while preserving cache_control, tool_use IDs, and errors."""
    threshold = min_chars or (350 if mode == "aggressive" else 600)
    if mode == "off" or not isinstance(body_obj, dict) or not isinstance(body_obj.get("messages"), list):
        return {
            "body": body_obj,
            "origTokens": 0,
            "compressedTokens": 0,
            "savedTokens": 0,
            "savedPct": 0.0,
            "blocksCompressed": 0,
            "rulesApplied": [],
        }

    orig_tokens = 0
    compressed_tokens = 0
    blocks_compressed = 0
    rules_seen: list[str] = []

    def add_rule(r: str) -> None:
        if r not in rules_seen:
            rules_seen.append(r)

    def compress_str(s: str) -> str:
        nonlocal orig_tokens, compressed_tokens, blocks_compressed
        if not isinstance(s, str) or len(s) < threshold:
            return s
        before_tok = estimate_tokens(s)
        slimmed = _slim_json_payload(s, mode)
        if slimmed is not None:
            after_tok = estimate_tokens(slimmed)
            if after_tok < before_tok:
                orig_tokens += before_tok
                compressed_tokens += after_tok
                blocks_compressed += 1
                add_rule("proxy-json-slim")
                return slimmed
        cmp = compress_tool_output(s, mode=mode, max_lines=50 if mode == "aggressive" else 95)
        if cmp["savedTokens"] > 0:
            orig_tokens += cmp["origTokens"]
            compressed_tokens += cmp["compressedTokens"]
            blocks_compressed += 1
            for r in cmp["rulesApplied"]:
                add_rule(r)
            return cmp["text"]
        return s

    next_messages = []
    for msg in body_obj["messages"]:
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            next_messages.append(msg)
            continue
        changed = False
        next_content = []
        for block in msg["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("cache_control"):
                next_content.append(block)
                continue
            bc = block.get("content")
            if isinstance(bc, str):
                nxt = compress_str(bc)
                if nxt != bc:
                    changed = True
                    next_content.append({**block, "content": nxt})
                else:
                    next_content.append(block)
            elif isinstance(bc, list):
                inner_changed = False
                next_parts = []
                for part in bc:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) and not part.get("cache_control"):
                        nxt = compress_str(part["text"])
                        if nxt != part["text"]:
                            inner_changed = True
                            next_parts.append({**part, "text": nxt})
                            continue
                    next_parts.append(part)
                if inner_changed:
                    changed = True
                    next_content.append({**block, "content": next_parts})
                else:
                    next_content.append(block)
            else:
                next_content.append(block)
        next_messages.append({**msg, "content": next_content} if changed else msg)

    saved_tokens = max(0, orig_tokens - compressed_tokens)
    saved_pct = round((saved_tokens / orig_tokens) * 100, 1) if orig_tokens > 0 else 0.0
    return {
        "body": {**body_obj, "messages": next_messages} if blocks_compressed > 0 else body_obj,
        "origTokens": orig_tokens,
        "compressedTokens": compressed_tokens,
        "savedTokens": saved_tokens,
        "savedPct": saved_pct,
        "blocksCompressed": blocks_compressed,
        "rulesApplied": rules_seen,
    }


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
    "x-backchannel-route",
}


class HeadroomProxyServer:
    """Managed threaded HTTP proxy supporting both primary upstream and /omni -> OmniRoute."""

    def __init__(
        self,
        *,
        port: int = 4243,
        upstream: str | None = None,
        omni_upstream: str | None = None,
        data_dir: str | Path | None = None,
        mode: str | None = None,
        on_saving: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.mode_override = mode
        self.on_saving = on_saving
        cfg = load_config(data_dir)
        proxy_port_opt = port or cfg.get("proxyPort", 4243)
        self.upstream_str = resolve_proxy_upstream(cfg, upstream=upstream, proxy_port=proxy_port_opt)
        self.omni_str = resolve_omniroute_upstream(cfg, omni_upstream=omni_upstream, proxy_port=proxy_port_opt)
        self.upstream_url = urlparse(self.upstream_str)
        self.omni_url = urlparse(self.omni_str)
        self._lock = threading.Lock()
        self.stats: dict[str, Any] = {
            "startedAt": iso_now(),
            "upstream": self.upstream_str,
            "omniUpstream": self.omni_str,
            "requestsProxied": 0,
            "requestsCompressed": 0,
            "omniRequestsProxied": 0,
            "omniRequestsCompressed": 0,
            "totalOrigTokens": 0,
            "totalSavedTokens": 0,
        }
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = port

    def start(self) -> int:
        proxy_self = self

        class ProxyHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _read_request_body(self) -> bytes:
                te = (self.headers.get("Transfer-Encoding") or "").lower()
                if "chunked" in te:
                    chunks = []
                    while True:
                        line = self.rfile.readline().strip()
                        if not line:
                            break
                        size = int(line.split(b";")[0], 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.readline()
                    return b"".join(chunks)
                cl = self.headers.get("Content-Length")
                if cl:
                    return self.rfile.read(int(cl))
                return b""

            def _handle_all(self) -> None:
                raw_url = self.path or "/"
                if self.command == "GET" and raw_url == "/_backchannel/health":
                    with proxy_self._lock:
                        payload = json.dumps({"ok": True, **proxy_self.stats}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                route_hdr = (self.headers.get("x-backchannel-route") or "").lower()
                has_omni = raw_url == "/omni" or raw_url.startswith("/omni/") or raw_url.startswith("/omni?")
                is_omni = has_omni or route_hdr == "omni"
                effective_url = (raw_url[5:] or "/") if has_omni else raw_url
                target_url = proxy_self.omni_url if is_omni else proxy_self.upstream_url

                with proxy_self._lock:
                    proxy_self.stats["requestsProxied"] += 1
                    if is_omni:
                        proxy_self.stats["omniRequestsProxied"] += 1

                try:
                    body_bytes = self._read_request_body()
                except Exception as exc:
                    err = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return

                content_type = self.headers.get("Content-Type") or ""
                req_path = effective_url.split("?")[0]
                is_messages_post = (
                    self.command == "POST"
                    and req_path == "/v1/messages"
                    and "application/json" in content_type.lower()
                )

                if is_messages_post and body_bytes:
                    try:
                        parsed = json.loads(body_bytes.decode("utf-8"))
                        cfg = load_config(proxy_self.data_dir)
                        mode = proxy_self.mode_override or cfg.get("compression") or "on"
                        cmp = compress_anthropic_messages_body(parsed, mode=mode)
                        if cmp["savedTokens"] > 0:
                            body_bytes = json.dumps(cmp["body"]).encode("utf-8")
                            with proxy_self._lock:
                                proxy_self.stats["requestsCompressed"] += 1
                                if is_omni:
                                    proxy_self.stats["omniRequestsCompressed"] += 1
                                proxy_self.stats["totalOrigTokens"] += cmp["origTokens"]
                                proxy_self.stats["totalSavedTokens"] += cmp["savedTokens"]
                            rec = record_compression_saving(
                                {
                                    "source": "proxy:omni:/v1/messages" if is_omni else "proxy:/v1/messages",
                                    "label": f"{parsed.get('model') or ('omniroute' if is_omni else 'claude')} ({cmp['blocksCompressed']} tool_result)",
                                    "mode": mode,
                                    "origTokens": cmp["origTokens"],
                                    "compressedTokens": cmp["compressedTokens"],
                                    "savedTokens": cmp["savedTokens"],
                                    "savedPct": cmp["savedPct"],
                                    "rulesApplied": cmp["rulesApplied"],
                                },
                                proxy_self.data_dir,
                            )
                            if proxy_self.on_saving:
                                proxy_self.on_saving(rec)
                    except Exception:
                        pass

                suffix = effective_url if effective_url.startswith("/") else f"/{effective_url}"
                base_path = "" if target_url.path in ("", "/") else target_url.path.rstrip("/")
                target_path = f"{base_path}{suffix}"

                fwd_headers: dict[str, str] = {}
                for k, v in self.headers.items():
                    if k.lower() not in _HOP_BY_HOP:
                        fwd_headers[k] = v
                fwd_headers["Host"] = target_url.netloc
                if body_bytes:
                    fwd_headers["Content-Length"] = str(len(body_bytes))

                conn: http.client.HTTPConnection | None = None
                try:
                    up_port = target_url.port or (443 if target_url.scheme == "https" else 80)
                    if target_url.scheme == "https":
                        conn = http.client.HTTPSConnection(
                            target_url.hostname or "127.0.0.1",
                            up_port,
                            timeout=300,
                            context=ssl.create_default_context(),
                        )
                    else:
                        conn = http.client.HTTPConnection(target_url.hostname or "127.0.0.1", up_port, timeout=300)
                    conn.request(self.command, target_path, body=body_bytes if body_bytes else None, headers=fwd_headers)
                    up_res = conn.getresponse()

                    self.send_response(up_res.status)
                    res_cl = up_res.getheader("Content-Length")
                    is_chunked_out = res_cl is None and self.command != "HEAD"
                    for hk, hv in up_res.getheaders():
                        hkl = hk.lower()
                        if hkl in ("transfer-encoding", "connection", "keep-alive"):
                            continue
                        if is_chunked_out and hkl == "content-length":
                            continue
                        self.send_header(hk, hv)
                    if is_chunked_out:
                        self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Connection", "close")
                    self.end_headers()

                    if self.command != "HEAD":
                        while True:
                            chunk = up_res.read(4096)
                            if not chunk:
                                break
                            if is_chunked_out:
                                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                            else:
                                self.wfile.write(chunk)
                            self.wfile.flush()
                        if is_chunked_out:
                            self.wfile.write(b"0\r\n\r\n")
                            self.wfile.flush()
                    self.close_connection = True
                except BrokenPipeError:
                    self.close_connection = True
                except Exception as exc:
                    err = json.dumps({"error": f"Headroom proxy upstream error: {exc}"}).encode("utf-8")
                    try:
                        self.send_response(502)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(err)))
                        self.end_headers()
                        self.wfile.write(err)
                    except Exception:
                        pass
                    self.close_connection = True
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            do_GET = _handle_all
            do_POST = _handle_all
            do_PUT = _handle_all
            do_PATCH = _handle_all
            do_DELETE = _handle_all
            do_OPTIONS = _handle_all
            do_HEAD = _handle_all

        class ReusableThreadingHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._httpd = ReusableThreadingHTTPServer(("127.0.0.1", self.port), ProxyHandler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
