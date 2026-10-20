#!/usr/bin/env python3
"""Pre-flight check for packaging/win/g4f-proxy.spec - no PyInstaller needed.

Verifies three things that silently break frozen builds:
  1. every g4f module the spec freezes is importable *by name* (no typos)
  2. the optional third-party packages the spec collects actually exist
  3. the data files read through ``__file__`` at runtime are present

    python packaging/win/validate_spec.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
G4F = ROOT / "g4f"

REQUIRED_PACKAGES = [
    "curl_cffi",
    "primp",
    "cryptography",
    "Cryptodome",
    "lxml",
    "yarl",
    "multidict",
    "frozenlist",
    "propcache",
    "pydantic_core",
    "brotli",
    "ddgs",
    "a2wsgi",
    "nest_asyncio2",
]

REQUIRED_DATA = [
    "g4f/providers.json",
    "g4f/gui/server/providers.html",
    "g4f/Provider/glm/AliyunCaptcha.js.txt",
    "g4f/Provider/needs_auth/deepseek/pow_solver.wasm",
    "g4f/mcp/claude_desktop_config.example.json",
]

UVICORN_MODULES = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]


def g4f_modules() -> list[str]:
    """Mirror of the spec's source-tree walk."""
    mods = []
    for py in sorted(G4F.rglob("*.py")):
        parts = list(py.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        dotted = ".".join(parts)
        if dotted.startswith("g4f.integration.markitdown"):
            continue
        mods.append(dotted)
    return mods


def main() -> int:
    errors: list[str] = []

    mods = g4f_modules()
    missing = [m for m in mods if importlib.util.find_spec(m) is None]
    print(f"g4f modules to freeze : {len(mods)}")
    if missing:
        errors.append(f"modules not importable: {missing[:5]}")

    print(f"third-party packages  : {len(REQUIRED_PACKAGES)}")
    for pkg in REQUIRED_PACKAGES:
        if importlib.util.find_spec(pkg) is None:
            errors.append(f"missing package: {pkg}")

    for mod in UVICORN_MODULES:
        if importlib.util.find_spec(mod) is None:
            errors.append(f"missing uvicorn module: {mod}")

    print(f"data files            : {len(REQUIRED_DATA)}")
    for rel in REQUIRED_DATA:
        if not (ROOT / rel).exists():
            errors.append(f"missing data file: {rel}")

    if errors:
        print("\nFAILED")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nOK - spec inputs are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
