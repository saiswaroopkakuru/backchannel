#!/usr/bin/env python3
"""Direct MCP stdio server entry point (works with or without pip install)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backchannel.mcp import run_stdio_server  # noqa: E402

if __name__ == "__main__":
    run_stdio_server()
