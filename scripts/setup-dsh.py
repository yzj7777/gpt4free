#!/usr/bin/env python3
"""Thin wrapper kept for scripts/docs that call ``python scripts/setup-dsh.py``.

The implementation lives in ``g4f/cli/dsh_setup.py`` so that the frozen Windows
build (``g4f-proxy.exe --dsh``) can reuse it without shipping a second copy.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from g4f.cli.dsh_setup import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
