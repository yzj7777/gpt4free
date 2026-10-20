"""PyInstaller entry point for the frozen Windows build (``g4f-proxy.exe``)."""

import multiprocessing
import sys

from g4f.cli.api_launcher import main

if __name__ == "__main__":
    # frozen apps on Windows must call this before spawning anything
    multiprocessing.freeze_support()
    sys.exit(main())
