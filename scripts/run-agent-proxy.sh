#!/usr/bin/env bash
#
# One-command launcher for g4f as a local OpenAI-compatible reverse proxy
# (pip/venv flavour — no uv required).
#
#   bash scripts/run-agent-proxy.sh              # install deps, write routes, start on :8080
#   bash scripts/run-agent-proxy.sh --dsh        # ... and register the provider in ~/.dsh
#   bash scripts/run-agent-proxy.sh --dsh --launch-dsh   # ... and start dsh web
#
# This script only prepares the environment: the actual work (catalog cache, API
# key, routes, dsh merge, server) lives in g4f/cli/api_launcher.py so that the
# shell, `uv run g4f-api` and the frozen Windows exe share one implementation.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${G4F_VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"
DO_INSTALL=1
ARGS=()

usage() {
  cat <<EOF
Usage: bash scripts/run-agent-proxy.sh [options]

  --port N            listen port (default: 8080, env G4F_PORT)
  --bind ADDR         listen address (default: 0.0.0.0, env G4F_BIND)
  --dsh               also write/merge the provider into \$DSH_HOME/settings.yaml
  --launch-dsh        start \`npx @deepseek-ai/dsh web\` once the proxy is ready
  --models a,b,c      model ids registered in dsh (default: agent-primary,agent-fast,agent-quality)
  --set-default       make agent-primary the dsh default model
  --reset-routes      overwrite ~/.g4f/cookies/config.yaml (a .bak is kept)
  --rotate-key        generate a new API key
  --no-install        skip pip install (deps already present)
  --no-start          configure only, print credentials, do not start the server
  -h, --help          this help

Everything else is forwarded to \`python -m g4f.cli.api_launcher --help\`.
Env: G4F_API_KEY, G4F_COOKIES_DIR, G4F_VENV, DSH_HOME.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install) DO_INSTALL=0; shift ;;
    --no-start) ARGS+=(--print); shift ;;
    --port|--bind|--models)
      [[ $# -ge 2 ]] || { echo "missing value for $1" >&2; exit 2; }
      ARGS+=("$1" "$2"); shift 2 ;;
    --dsh|--launch-dsh|--set-default|--reset-routes|--rotate-key|--json)
      ARGS+=("$1"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

say() { printf '\033[1;36m▸\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- python + deps
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  say "creating venv at $VENV"
  python3 -m venv "$VENV"
  "$PY" -m pip install -q --upgrade pip
  DO_INSTALL=1
fi

STAMP="$VENV/.g4f-deps-stamp"
if [[ "$DO_INSTALL" == "1" ]]; then
  if [[ -f "$STAMP" && "$STAMP" -nt "$ROOT/requirements.txt" ]]; then
    say "dependencies already installed"
  else
    say "installing requirements (first run takes ~1-2 min)"
    "$PY" -m pip install -q -r "$ROOT/requirements.txt"
    touch "$STAMP"
  fi
else
  say "skipping dependency install (--no-install)"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m g4f.cli.api_launcher "${ARGS[@]}"
