# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the one-click Windows build.
#
#   powershell -ExecutionPolicy Bypass -File packaging\win\build-exe.ps1
#
# Produces, depending on G4F_ONEFILE:
#   1 -> dist\g4f-proxy.exe            single file, ~110 MB, 4-8 s cold start
#   0 -> dist\g4f-proxy\g4f-proxy.exe  folder build, ~1 s start, ships as a zip
#
# Nothing here imports g4f at build time: provider modules are discovered by
# walking the source tree, so the build works offline and cannot be broken by a
# provider that needs the network to import.

import os
import pathlib

ONEFILE = os.environ.get("G4F_ONEFILE", "1") != "0"

ROOT = pathlib.Path(SPECPATH).parent.parent  # noqa: F821  (SPECPATH is injected)
G4F = ROOT / "g4f"

# --------------------------------------------------------------------------- #
# hidden imports: every g4f module, without importing the package
# --------------------------------------------------------------------------- #
hiddenimports = []
for py in sorted(G4F.rglob("*.py")):
    rel = py.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    dotted = ".".join(parts)
    # optional document-conversion integration: pulls markitdown[all] (100 MB+)
    if dotted.startswith("g4f.integration.markitdown"):
        continue
    hiddenimports.append(dotted)

# uvicorn picks its loop/protocol/lifespan implementations through strings
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# --------------------------------------------------------------------------- #
# binaries / data of compiled dependencies
# --------------------------------------------------------------------------- #
from PyInstaller.utils.hooks import collect_all  # noqa: E402

binaries = []
datas = []
for pkg in (
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
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception as exc:  # optional package missing -> skip quietly
        print(f"[spec] skipped {pkg}: {exc}")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# --------------------------------------------------------------------------- #
# data files read from __file__ at runtime
# --------------------------------------------------------------------------- #
for rel, target in (
    ("g4f/providers.json", "g4f"),
    ("g4f/gui/server/providers.html", "g4f/gui/server"),
    ("g4f/Provider/glm/AliyunCaptcha.js.txt", "g4f/Provider/glm"),
    ("g4f/Provider/needs_auth/deepseek/pow_solver.wasm", "g4f/Provider/needs_auth/deepseek"),
    ("g4f/mcp/claude_desktop_config.example.json", "g4f/mcp"),
):
    src = ROOT / rel
    if src.exists():
        datas.append((str(src), target))
    else:
        print(f"[spec] missing data file (skipped): {rel}")

# --------------------------------------------------------------------------- #
# trimming: features this build does not ship
# --------------------------------------------------------------------------- #
excludes = [
    "tkinter",
    "wasmtime",          # deepseek PoW solver (browser-only provider, not used)
    "pystray",           # tray icon
    "markitdown",        # document conversion
    "cairosvg",          # svg -> png
    "gpt4all",           # local models
    "torch",
    "matplotlib",
    "IPython",
    "pytest",
    "PyQt5",
    "PySide6",
    "playwright",
    "selenium",
]

block_cipher = None

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "win" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

if ONEFILE:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="g4f-proxy",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="g4f-proxy",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="g4f-proxy",
    )
