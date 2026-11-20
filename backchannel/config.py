"""Shared persistent configuration and upstream URL resolution for backchannel."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_CONFIG: dict[str, Any] = {
    "voice": "terse",  # Caveman: off | terse | ultra | megacave
    "minimalism": "full",  # Ponytail: off | lite | full | ultra
    "compression": "on",  # Headroom: off | on | aggressive
    "graphAssist": True,  # Graphify: route search via .backchannel/graph.json
    "memoryAssist": True,  # Claude-Mem: cross-session recall & capture
    "budget5hUsd": 25.0,
    "budget7dUsd": 150.0,
    "dashboardPort": 4242,
    "proxyPort": 4243,
    "proxyUpstream": "https://api.anthropic.com",
    "omniRouteUrl": "http://127.0.0.1:20128",
}

VALID_ENUMS: dict[str, tuple[str, ...]] = {
    "voice": ("off", "terse", "ultra", "megacave"),
    "minimalism": ("off", "lite", "full", "ultra"),
    "compression": ("off", "on", "aggressive"),
}

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def get_data_dir(override_dir: str | Path | None = None) -> Path:
    if override_dir:
        return Path(override_dir)
    env_dir = os.environ.get("BACKCHANNEL_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".backchannel"


def get_config_path(override_dir: str | Path | None = None) -> Path:
    return get_data_dir(override_dir) / "config.json"


def sanitize_config(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return out

    if raw.get("voice") in VALID_ENUMS["voice"]:
        out["voice"] = raw["voice"]
    if raw.get("minimalism") in VALID_ENUMS["minimalism"]:
        out["minimalism"] = raw["minimalism"]
    if raw.get("compression") in VALID_ENUMS["compression"]:
        out["compression"] = raw["compression"]
    if isinstance(raw.get("graphAssist"), bool):
        out["graphAssist"] = raw["graphAssist"]
    if isinstance(raw.get("memoryAssist"), bool):
        out["memoryAssist"] = raw["memoryAssist"]

    for key in ("budget5hUsd", "budget7dUsd"):
        val = raw.get(key)
        try:
            num = float(val)  # type: ignore[arg-type]
            if num > 0:
                out[key] = round(num, 2)
        except (TypeError, ValueError):
            pass

    for key in ("dashboardPort", "proxyPort"):
        val = raw.get(key)
        try:
            port = round(float(val))  # type: ignore[arg-type]
            if 1024 <= port <= 65535:
                out[key] = int(port)
        except (TypeError, ValueError):
            pass

    for key in ("proxyUpstream", "omniRouteUrl"):
        val = raw.get(key)
        if isinstance(val, str) and _HTTP_URL_RE.match(val.strip()):
            out[key] = val.strip()

    return out


def load_config(override_dir: str | Path | None = None) -> dict[str, Any]:
    cfg_path = get_config_path(override_dir)
    if not cfg_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        parsed = json.loads(cfg_path.read_text(encoding="utf-8"))
        return sanitize_config(parsed)
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(
    patch: dict[str, Any] | None = None, override_dir: str | Path | None = None
) -> dict[str, Any]:
    current = load_config(override_dir)
    merged = {**current, **(patch or {})}
    nxt = sanitize_config(merged)
    data_dir = get_data_dir(override_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    get_config_path(override_dir).write_text(
        json.dumps(nxt, indent=2) + "\n", encoding="utf-8"
    )
    return nxt


def is_loopback_proxy_url(raw_url: str | None, proxy_port: int = 4243) -> bool:
    try:
        u = urlparse(str(raw_url or "").strip())
        host = (u.hostname or "").lower()
        is_local = host in ("127.0.0.1", "localhost", "::1")
        port = u.port or (443 if u.scheme == "https" else 80)
        return is_local and int(port) == int(proxy_port)
    except Exception:
        return False


def detect_claude_upstream_url(
    proxy_port: int = 4243, settings_path: str | Path | None = None
) -> str | None:
    """Detect pre-existing ANTHROPIC_BASE_URL in ~/.claude/settings.json so proxy chains cleanly."""
    path = Path(settings_path) if settings_path else Path.home() / ".claude" / "settings.json"
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        candidate = str((parsed.get("env") or {}).get("ANTHROPIC_BASE_URL") or "").strip()
        if not candidate or not _HTTP_URL_RE.match(candidate):
            return None
        if is_loopback_proxy_url(candidate, proxy_port):
            return None
        return candidate.rstrip("/")
    except Exception:
        return None


def resolve_proxy_upstream(
    cfg: dict[str, Any] | None = None,
    *,
    upstream: str | None = None,
    proxy_port: int | None = None,
    claude_settings_path: str | Path | None = None,
) -> str:
    cfg = cfg or DEFAULT_CONFIG
    port = int(proxy_port or cfg.get("proxyPort") or DEFAULT_CONFIG["proxyPort"])
    cfg_up = cfg.get("proxyUpstream")
    candidates = [
        upstream,
        os.environ.get("BACKCHANNEL_UPSTREAM_URL"),
        cfg_up if cfg_up and cfg_up != DEFAULT_CONFIG["proxyUpstream"] else None,
        detect_claude_upstream_url(port, claude_settings_path),
        cfg_up,
        DEFAULT_CONFIG["proxyUpstream"],
    ]
    for raw in candidates:
        if isinstance(raw, str) and _HTTP_URL_RE.match(raw.strip()) and not is_loopback_proxy_url(raw, port):
            return raw.strip().rstrip("/")
    return str(DEFAULT_CONFIG["proxyUpstream"])


def read_omniroute_settings(settings_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(settings_path) if settings_path else Path.home() / ".claude" / "omniroute-settings.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_omniroute_upstream(
    cfg: dict[str, Any] | None = None,
    *,
    omni_upstream: str | None = None,
    proxy_port: int | None = None,
    omni_settings_path: str | Path | None = None,
) -> str:
    cfg = cfg or DEFAULT_CONFIG
    port = int(proxy_port or cfg.get("proxyPort") or DEFAULT_CONFIG["proxyPort"])
    omni_settings = read_omniroute_settings(omni_settings_path)
    detected = str(((omni_settings or {}).get("env") or {}).get("ANTHROPIC_BASE_URL") or "").strip() or None
    cfg_omni = cfg.get("omniRouteUrl")
    candidates = [
        omni_upstream,
        os.environ.get("BACKCHANNEL_OMNIROUTE_URL"),
        cfg_omni if cfg_omni and cfg_omni != DEFAULT_CONFIG["omniRouteUrl"] else None,
        detected,
        cfg_omni,
        DEFAULT_CONFIG["omniRouteUrl"],
    ]
    for raw in candidates:
        if isinstance(raw, str) and _HTTP_URL_RE.match(raw.strip()) and not is_loopback_proxy_url(raw, port):
            return raw.strip().rstrip("/")
    return str(DEFAULT_CONFIG["omniRouteUrl"])
