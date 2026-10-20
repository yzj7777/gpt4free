"""Register a local g4f reverse proxy as a provider in DeepSeek Harness (dsh).

DeepSeek Harness stores its model configuration in ``$DSH_HOME/settings.yaml``
(default ``~/.dsh/settings.yaml``).  A custom OpenAI-compatible endpoint is
declared under ``llm-pi-ai.providers``::

    llm-pi-ai:
      providers:
        g4f:
          displayName: g4f local proxy
          apiKeyEnv: G4F_API_KEY
          api: openai-completions
          baseURL: http://127.0.0.1:8080/v1
          compat:
            supportsDeveloperRole: false
            maxTokensField: max_tokens
          models:
            - id: agent-primary
              name: g4f Agent Primary

The block is merged into an existing file instead of overwriting it, a
timestamped backup is kept, and the operation is safe to repeat.

Usable three ways::

    python -m g4f.cli.dsh_setup --base-url http://127.0.0.1:8080/v1
    python scripts/setup-dsh.py --set-default
    g4f-api --dsh            # calls main() in-process, also in the frozen exe
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install PyYAML")

PLUGIN_ID = "llm-pi-ai"
DEFAULT_MODELS = ["agent-primary", "agent-fast", "agent-quality"]

PRETTY_NAMES = {
    "agent-primary": "g4f Agent Primary",
    "agent-fast": "g4f Agent Fast",
    "agent-quality": "g4f Agent Quality",
}


def model_entries(model_ids: List[str]) -> List[Dict[str, Any]]:
    return [{"id": mid, "name": PRETTY_NAMES.get(mid, mid)} for mid in model_ids]


def provider_block(args: argparse.Namespace, model_ids: List[str]) -> Dict[str, Any]:
    return {
        "displayName": "g4f local proxy",
        "apiKeyEnv": args.api_key_env,
        "api": "openai-completions",
        "baseURL": args.base_url,
        # g4f speaks plain OpenAI Chat Completions: no developer role and the
        # classic max_tokens field.  Without this, dsh may send the newer
        # OpenAI request shape and some gateways answer 400.
        "compat": {
            "supportsDeveloperRole": False,
            "maxTokensField": "max_tokens",
        },
        "defaultContextWindow": args.context_window,
        "defaultMaxTokens": args.max_tokens,
        "models": model_entries(model_ids),
    }


def merge_mapping(settings: Dict[str, Any], block: Dict[str, Any], args, model_ids):
    plugin = settings.setdefault(PLUGIN_ID, {})
    if not isinstance(plugin, dict):
        raise SystemExit(f"'{PLUGIN_ID}' in settings.yaml is not a mapping; fix it by hand first.")
    providers = plugin.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise SystemExit(f"'{PLUGIN_ID}.providers' is not a mapping; fix it by hand first.")

    existing = providers.get(args.provider_id) or {}
    if existing and not args.force:
        merged = dict(existing)
        merged.update({k: v for k, v in block.items() if k not in ("models", "compat")})
        # keep user's compat tweaks, add our defaults
        compat = dict(block.get("compat") or {})
        compat.update(existing.get("compat") or {})
        if compat:
            merged["compat"] = compat
        merged["models"] = block["models"]  # models are owned by this script
        providers[args.provider_id] = merged
    else:
        providers[args.provider_id] = block

    if args.set_default:
        settings["agent-default-model"] = {
            "provider": args.provider_id,
            "model": model_ids[0],
        }


def merge_plugin_list(settings: List[Any], block: Dict[str, Any], args, model_ids):
    entry = next(
        (item for item in settings if isinstance(item, dict) and item.get("id") == PLUGIN_ID),
        None,
    )
    if entry is None:
        entry = {"id": PLUGIN_ID, "config": {}}
        settings.append(entry)
    config = entry.setdefault("config", {})
    if not isinstance(config, dict):
        raise SystemExit(f"'{PLUGIN_ID}' plugin entry has a non-mapping config; fix it by hand first.")
    providers = config.setdefault("providers", {})
    existing = providers.get(args.provider_id) or {}
    merged = dict(existing)
    merged.update(block)
    providers[args.provider_id] = merged

    if args.set_default:
        default_entry = next(
            (
                item
                for item in settings
                if isinstance(item, dict) and item.get("id") == "agent-default-model"
            ),
            None,
        )
        value = {"provider": args.provider_id, "model": model_ids[0]}
        if default_entry is None:
            settings.append({"id": "agent-default-model", "config": value})
        else:
            default_entry.setdefault("config", {}).update(value)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="setup-dsh",
        description="Register a local g4f proxy in DeepSeek Harness settings.yaml",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    p.add_argument("--provider-id", default="g4f", help="lowercase id, permanent once created")
    p.add_argument("--api-key-env", default="G4F_API_KEY", help="env var holding the proxy API key")
    p.add_argument("--models", default=",".join(DEFAULT_MODELS), help="comma separated model ids")
    p.add_argument("--context-window", type=int, default=262144)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--dsh-home", default=os.environ.get("DSH_HOME") or str(Path.home() / ".dsh"))
    p.add_argument("--set-default", action="store_true", help="set agent-default-model to the first model")
    p.add_argument("--force", action="store_true", help="replace an existing provider entry instead of merging")
    p.add_argument("--api-key-file", default="", help="only used to print a ready-to-paste export line")
    p.add_argument("--dry-run", action="store_true", help="print the resulting YAML, do not write")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_ids:
        sys.exit("--models must contain at least one model id")

    home = Path(os.path.expanduser(args.dsh_home))
    path = home / "settings.yaml"
    block = provider_block(args, model_ids)

    if path.exists():
        raw = path.read_text(encoding="utf-8")
        settings: Any = yaml.safe_load(raw) if raw.strip() else {}
        if settings is None:
            settings = {}
    else:
        settings = {}

    if isinstance(settings, list):
        merge_plugin_list(settings, block, args, model_ids)
    elif isinstance(settings, dict):
        merge_mapping(settings, block, args, model_ids)
    else:
        sys.exit(f"unexpected YAML root in {path}: {type(settings).__name__}")

    output = yaml.safe_dump(settings, sort_keys=False, allow_unicode=True, width=100)

    if args.dry_run:
        print(f"# {path} (dry run)")
        print(output, end="")
        return 0

    home.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(f".yaml.bak.{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")
    path.write_text(output, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass

    print(f"wrote:  {path}")
    print(f"provider '{args.provider_id}' -> {args.base_url}")
    print(f"models:  {', '.join(model_ids)}")
    print()

    key_hint = args.api_key_env
    if args.api_key_file and Path(args.api_key_file).exists():
        key = Path(args.api_key_file).read_text(encoding="utf-8").strip()
        print("Export the key in the shell that starts dsh (dsh reads apiKeyEnv per request):")
        if sys.platform == "win32":
            print(f'  set {key_hint}={key}')
            print(f'  # PowerShell: $env:{key_hint}="{key}"')
        else:
            print(f"  export {key_hint}={key}")
    else:
        print("Export the key in the shell that starts dsh:")
        if sys.platform == "win32":
            print(f"  set {key_hint}=<your g4f api key>")
        else:
            print(f"  export {key_hint}=<your g4f api key>")
    print()
    print("Validate and start:")
    print(f"  npx @deepseek-ai/dsh provider validate {args.provider_id}   # if your dsh has this command")
    print("  npx @deepseek-ai/dsh web")
    if not args.set_default:
        print(f"\nPick provider '{args.provider_id}' and a model in Settings -> Models, or re-run with --set-default.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
