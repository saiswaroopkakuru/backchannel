#!/usr/bin/env python3
"""Direct Claude Code lifecycle hook entry point (works with or without pip install)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backchannel.hook import main  # noqa: E402

if __name__ == "__main__":
    main()
