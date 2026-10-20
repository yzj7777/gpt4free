"""One-command launcher for the OpenAI-compatible g4f API.

    uv run g4f-api                 # key + routes + server on 127.0.0.1:8080
    uv run g4f-api --print         # print credentials, do not start
    uv run g4f-api --rotate-key    # new API key, then start
    uv run g4f-api --dsh           # also register the provider for DeepSeek Harness
    g4f-proxy.exe                  # same thing, frozen Windows build

Everything is idempotent: the provider catalog cache, the API key and the route
file are reused on the next run unless you ask for a new one.

This module is the single entry point for every front-end:
  * ``uv run g4f-api``            (pyproject console script)
  * ``bash scripts/run-agent-proxy.sh`` (pip/venv path, calls this module too)
  * ``g4f-proxy.exe``             (PyInstaller one-file build for Windows)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))

DEFAULT_PORT = 8080
DEFAULT_MODELS = "agent-primary,agent-fast,agent-quality"
CATALOG_URL = "https://g4f.dev/dist/js/providers.json"

# Providers that need a real browser, or that are known-broken right now.  Keeping
# them out of the automatic pools avoids 30s stalls before a fallback is tried.
IGNORED_BASE = "Puter,Airforce,AgentTools"
IGNORED_NO_BROWSER = "Cloudflare,Qwen,ChatGPT,Pi,Arena,GLM"


# --------------------------------------------------------------------------- #
# console helpers
# --------------------------------------------------------------------------- #
def _enable_ansi() -> None:
    """Make ANSI colours work in the legacy Windows console."""
    if not IS_WINDOWS:
        return
    try:  # pragma: no cover - Windows only
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _say(msg: str) -> None:
    # progress goes to stderr so that `--json` stays machine readable
    print(f"\033[1;36m▸\033[0m {msg}", file=sys.stderr, flush=True)


def _warn(msg: str) -> None:
    print(f"\033[1;33m!\033[0m {msg}", file=sys.stderr, flush=True)


def _clipboard(text: str) -> bool:
    """Copy *text* to the system clipboard using whatever the OS provides."""
    candidates = (
        [["clip"]]
        if IS_WINDOWS
        else [["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"]]
    )
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, input=text.encode("utf-8"), check=False)
            if proc.returncode == 0:
                return True
        except (OSError, ValueError):
            continue
    return False


def _pause_on_exit() -> None:
    if not (FROZEN and sys.stdin and sys.stdin.isatty()):
        return
    try:
        input("\n按回车关闭窗口 / press Enter to close ...")
    except (EOFError, KeyboardInterrupt):
        pass


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def _default_cookies_dir() -> Path:
    """Same directory g4f itself reads (``%APPDATA%\\g4f\\cookies`` on Windows)."""
    try:
        from g4f.config import COOKIES_DIR

        return Path(COOKIES_DIR)
    except Exception:
        return Path.home() / ".g4f" / "cookies"


def _cache_dir() -> Path:
    from g4f.config import get_cache_dir

    return Path(get_cache_dir())


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


# --------------------------------------------------------------------------- #
# 1. provider catalog (offline safe)
# --------------------------------------------------------------------------- #
def seed_catalog(force: bool = False) -> Path:
    """Make sure g4f can import without a network round-trip to g4f.dev.

    ``g4f.providers.any_provider`` resolves providers from
    ``<cache>/.models/<date>/providers.json`` and falls back to downloading that
    file.  When the download fails the whole API server refuses to boot, so we
    pre-seed the cache - with the live catalog if reachable, with a minimal stub
    otherwise.
    """
    from datetime import date

    path = _cache_dir() / ".models" / date.today().strftime("%Y-%m-%d") / "providers.json"
    if path.exists() and not force:
        return path

    try:
        import requests

        resp = requests.get(CATALOG_URL, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        _say(f"fetched live provider catalog ({len(data.get('providers', {}))} entries)")
    except Exception as exc:  # offline / blocked → still bootable
        data = {
            "providers": {
                "default": {"baseUrl": "https://g4f.space/v1", "backupUrl": "https://g4f.space/v1"}
            },
            "defaultModels": {"default": "auto"},
        }
        _warn(f"live catalog unavailable ({type(exc).__name__}); using built-in stub")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 2. api key
# --------------------------------------------------------------------------- #
def resolve_key(key_file: Path, rotate: bool) -> tuple[str, str]:
    env_key = os.environ.get("G4F_API_KEY", "").strip()
    if env_key and not rotate:
        return env_key, "environment G4F_API_KEY"

    if key_file.exists() and not rotate:
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key, str(key_file)

    key = "g4f_" + secrets.token_urlsafe(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key, ("rotated → " + str(key_file) if rotate else str(key_file))


# --------------------------------------------------------------------------- #
# 3. routes
# --------------------------------------------------------------------------- #
ROUTES_HEAD = """\
# g4f model routes for agent use.
# Order matters: the first provider that answers wins, later ones are fallbacks.
# Evidence for this ordering: docs/community-provider-eval-2026-10.md
"""

ROUTES_PRIMARY = """\
models:
  - name: "agent-primary"
    providers:
      - provider: "KiloCode"
        model: "kilo-auto/free"
      - provider: "LLM7"
        model: "default"
      - provider: "Perplexity"
        model: "auto"
        condition: "error_count < 3"
"""

ROUTES_TAIL_BROWSER = """\
      - provider: "Cloudflare"
        model: "glm-5.2"          # slow but very stable, needs Chrome/Chromium
"""

ROUTES_TAIL_PLAIN = """\
      - provider: "OpenRouterFree"
        model: "auto"
      - provider: "Nvidia"
        model: "meta/llama-3.3-70b-instruct"
"""

ROUTES_REST = """
  - name: "agent-fast"
    providers:
      - provider: "Groq"
        model: "openai/gpt-oss-120b"
      - provider: "KiloCode"
        model: "kilo-auto/free"
      - provider: "LLM7"
        model: "default"

  - name: "agent-quality"
    providers:
      - provider: "GeminiPro"
        model: "gemini-2.5-flash"
      - provider: "Groq"
        model: "openai/gpt-oss-120b"
      - provider: "KiloCode"
        model: "kilo-auto/free"
"""


def browser_available() -> bool:
    """True when a Chrome/Chromium binary (or Lightpanda) can be driven by g4f."""
    try:
        from g4f.requests.cdp import find_chrome_path, find_lightpanda_path

        return bool(find_chrome_path() or find_lightpanda_path())
    except Exception:
        return False


def write_routes(routes_file: Path, has_browser: bool, reset: bool) -> bool:
    """Write the agent route table. Returns True when the file was (re)written."""
    if routes_file.exists() and not reset:
        return False

    if routes_file.exists():
        backup = routes_file.with_suffix(f".yaml.bak.{time.strftime('%Y%m%d%H%M%S')}")
        backup.write_text(routes_file.read_text(encoding="utf-8"), encoding="utf-8")
        _say(f"backed up previous routes → {backup.name}")

    body = (
        ROUTES_HEAD
        + ROUTES_PRIMARY
        + (ROUTES_TAIL_BROWSER if has_browser else ROUTES_TAIL_PLAIN)
        + ROUTES_REST
    )
    routes_file.parent.mkdir(parents=True, exist_ok=True)
    routes_file.write_text(body, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# 4. DeepSeek Harness
# --------------------------------------------------------------------------- #
def register_dsh(args, base_url: str, key_file: Path) -> bool:
    """Merge the provider block into $DSH_HOME/settings.yaml (in-process)."""
    import contextlib
    import io

    from g4f.cli.dsh_setup import main as dsh_main

    argv = [
        "--base-url",
        base_url,
        "--api-key-env",
        "G4F_API_KEY",
        "--models",
        args.models,
        "--api-key-file",
        str(key_file),
    ]
    if args.set_default:
        argv.append("--set-default")
    if args.dsh_home:
        argv += ["--dsh-home", args.dsh_home]
    # keep stdout clean for `--json`
    stream = sys.stderr if getattr(args, "json", False) else sys.stdout
    try:
        with contextlib.redirect_stdout(stream):
            return dsh_main(argv) == 0
    except SystemExit as exc:  # dsh_main may sys.exit() on bad input
        return exc.code in (0, None)


# --------------------------------------------------------------------------- #
# 5. summary panel
# --------------------------------------------------------------------------- #
def print_panel(base_url: str, api_key: str, key_source: str, routes: Path, args) -> None:
    line = "─" * 62
    masked = api_key[:8] + "…" if len(api_key) > 8 else api_key
    print()
    print(line)
    print(f" base URL  : {base_url}")
    print(f" api key   : {masked}   ({key_source})")
    print(f" routes    : {routes}")
    print()
    print(" OpenAI-compatible clients:")
    print(f"   OPENAI_BASE_URL={base_url}")
    print(f"   OPENAI_API_KEY={api_key}")
    print()
    print(" curl:")
    print(f'   curl -H "Authorization: Bearer {api_key}" {base_url}/models')
    if args.dsh:
        print()
        print(" DeepSeek Harness:")
        if IS_WINDOWS:
            print(f"   set G4F_API_KEY={api_key}")
        else:
            print(f"   export G4F_API_KEY={api_key}")
        print("   npx @deepseek-ai/dsh web")
        print("   # then pick provider 'g4f' → model 'agent-primary'")
    print(line)
    print()


# --------------------------------------------------------------------------- #
# 6. server
# --------------------------------------------------------------------------- #
def _apply_env(args, api_key: str, has_browser: bool) -> dict:
    env = dict(os.environ)
    env["G4F_API_KEY"] = api_key
    env.setdefault("G4F_TIMEOUT", "120")
    env.setdefault("G4F_STREAM_TIMEOUT", "120")
    if not env.get("G4F_IGNORED_PROVIDERS"):
        ignored = IGNORED_BASE if has_browser else f"{IGNORED_BASE},{IGNORED_NO_BROWSER}"
        env["G4F_IGNORED_PROVIDERS"] = ignored
    os.environ.update({k: v for k, v in env.items() if k.startswith("G4F_")})
    return env


def _serve_inprocess(args) -> int:
    """Frozen builds: run uvicorn in this process (no python.exe to spawn)."""
    from g4f.api import AppConfig, run_api
    from g4f.Provider import ProviderLoader

    ignored = os.environ.get("G4F_IGNORED_PROVIDERS", "")
    ProviderLoader.ignored = [p.strip() for p in ignored.split(",") if p.strip()]
    AppConfig.load_from_env()

    try:
        # run_api() splits bind on ":", so a bare host crashes it - always host:port
        run_api(bind=f"{args.host}:{args.port}", use_colors=True)
    except KeyboardInterrupt:
        return 130
    return 0


def serve(args, api_key: str, has_browser: bool) -> int:
    env = _apply_env(args, api_key, has_browser)

    if FROZEN:
        _say(f"starting g4f API on {args.host}:{args.port}")
        return _serve_inprocess(args)

    cmd = [sys.executable, "-m", "g4f", "--no-gui", "--bind", f"{args.host}:{args.port}"]
    _say(f"starting g4f API on {args.host}:{args.port}")
    proc = subprocess.Popen(cmd, env=env)

    deadline = time.time() + 45
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc.returncode or 1
        if _port_open(args.port):
            ready = True
            break
        time.sleep(0.4)

    if ready:
        _say(f"proxy is ready → http://127.0.0.1:{args.port}/v1")
    else:
        _warn("port did not open within 45s; check the log above")

    if args.launch_dsh:
        try:
            return subprocess.call(["npx", "-y", "@deepseek-ai/dsh", "web"], env=env)
        except FileNotFoundError:
            _warn("npx not found; install Node ^22.19 or >=24 first")

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 130


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    default_host = os.environ.get("G4F_BIND") or ("127.0.0.1" if IS_WINDOWS else "0.0.0.0")
    parser = argparse.ArgumentParser(
        prog="g4f-api",
        description="Start the OpenAI-compatible g4f API with an API key and agent routes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  g4f-api                             # everything, defaults
  g4f-api --port 9000 --dsh           # custom port + DeepSeek Harness provider
  g4f-api --host 0.0.0.0              # expose to the LAN (opens the firewall)
  g4f-api --print --json              # machine-readable key + base URL
  g4f-api --rotate-key                # revoke the old key, start with a new one
""",
    )
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=int(os.environ.get("G4F_PORT", DEFAULT_PORT)))
    parser.add_argument("--bind", default=None, metavar="HOST:PORT", help="shorthand for --host/--port")
    parser.add_argument(
        "--key-file",
        default=os.environ.get("G4F_KEY_FILE", ".g4f-api-key"),
        type=Path,
    )
    parser.add_argument("--rotate-key", action="store_true", help="generate a fresh API key")
    parser.add_argument("--routes", default=None, type=Path, help="route file (default: g4f cookies dir)")
    parser.add_argument("--reset-routes", action="store_true", help="overwrite an existing route file")
    parser.add_argument("--models", default=DEFAULT_MODELS, help="model ids registered in dsh")
    parser.add_argument("--dsh", action="store_true", help="register the provider in $DSH_HOME/settings.yaml")
    parser.add_argument("--set-default", action="store_true", help="make agent-primary the dsh default")
    parser.add_argument("--dsh-home", default=None, help="override $DSH_HOME")
    parser.add_argument("--launch-dsh", action="store_true", help="start `npx @deepseek-ai/dsh web` when ready")
    parser.add_argument("--print", dest="print_only", action="store_true", help="print credentials and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the panel")
    parser.add_argument("--copy", dest="copy_key", action="store_true", help="copy the API key to the clipboard")
    parser.add_argument("--no-copy", dest="copy_key", action="store_false", help="never touch the clipboard")
    parser.add_argument("--no-browser-detect", action="store_true", help="assume no Chrome/Lightpanda")
    parser.set_defaults(copy_key=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _enable_ansi()
    args = build_parser().parse_args(argv)

    explicit_port = args.bind is not None or "--port" in (argv if argv is not None else sys.argv)
    if args.bind:
        host, _, port = args.bind.rpartition(":")
        if not host or not port.isdigit():
            _warn("--bind must be HOST:PORT, e.g. 127.0.0.1:8080")
            return 2
        args.host, args.port = host, int(port)

    # A busy default port is common (another copy is already running). Bump it
    # instead of dying with an uvicorn traceback, unless the user was explicit.
    if not explicit_port and _port_open(args.port):
        for candidate in range(args.port + 1, args.port + 11):
            if not _port_open(candidate):
                _warn(f"port {args.port} is busy, using {candidate}")
                args.port = candidate
                break

    args.key_file = args.key_file.expanduser().resolve()
    routes_file = (
        args.routes.expanduser()
        if args.routes
        else Path(os.environ.get("G4F_COOKIES_DIR") or _default_cookies_dir())
    )
    routes_file = routes_file.resolve()
    if routes_file.is_dir():
        routes_file = routes_file / "config.yaml"

    base_url = f"http://127.0.0.1:{args.port}/v1"

    seed_catalog()
    api_key, key_source = resolve_key(args.key_file, args.rotate_key)
    _say(f"api key {key_source}")

    has_browser = False if args.no_browser_detect else browser_available()
    _say("browser: " + ("found" if has_browser else "none → HTTP-only fallbacks"))
    if write_routes(routes_file, has_browser, args.reset_routes):
        _say(f"wrote routes → {routes_file}")
    else:
        _say(f"keeping existing routes → {routes_file}")

    if args.dsh or args.launch_dsh:
        register_dsh(args, base_url, args.key_file)

    if args.json:
        print(
            json.dumps(
                {
                    "base_url": base_url,
                    "api_key": api_key,
                    "models": args.models.split(","),
                    "routes": str(routes_file),
                    "key_file": str(args.key_file),
                },
                indent=2,
            )
        )
        return 0

    print_panel(base_url, api_key, key_source, routes_file, args)

    if args.print_only:
        return 0

    copy_key = args.copy_key if args.copy_key is not None else FROZEN
    if copy_key and _clipboard(api_key):
        _say("api key copied to the clipboard")

    try:
        code = serve(args, api_key, has_browser)
    except KeyboardInterrupt:
        return 130
    except Exception:
        import traceback

        traceback.print_exc()
        code = 1
    if code != 130:
        # keep a double-clicked console window open so the last lines are readable
        _pause_on_exit()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
