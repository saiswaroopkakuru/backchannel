#!/usr/bin/env python3
"""Direct CLI entry point (works from any working directory, with or without pip install)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backchannel.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
