#!/usr/bin/env python3
"""
Agent-suitability benchmark for g4f providers / OpenAI-compatible endpoints.

It answers three questions for every candidate:

1. Does it work at all right now (auth, rate limit, network)?
2. Is it fast enough for an agent loop (TTFT, tokens/s, total latency)?
3. Is the quality / tool-calling good enough for agent use?

Two modes
---------
Provider mode (default), drives the library directly:

    python scripts/bench_providers.py --list
    python scripts/bench_providers.py --providers Pollinations,Qwen,Gemini
    python scripts/bench_providers.py --all-public --concurrency 3
    python scripts/bench_providers.py --all --include-auth --json out.json

Endpoint mode, benchmarks a running OpenAI-compatible server (e.g. your own
g4f reverse proxy):

    python scripts/bench_providers.py --base-url http://127.0.0.1:8080/v1 \
        --api-key $G4F_API_KEY --models auto,gpt-4o-mini

Notes
-----
* Providers that need cookies/keys (``needs_auth``) are skipped by default.
* Tool calling is tested natively (``tools=[...]`` on the provider). Providers
  without native tool support can still be agent-usable through g4f's tool
  emulation, which the HTTP API enables automatically; see ``--emulate-tools``.
* Token counts are estimates (usage from the provider is used when available).
* Recipes: nothing is cached between runs, every case is a fresh request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _ensure_g4f_importable() -> None:
    """Allow running the script from a checkout without installing g4f."""
    try:
        import g4f  # noqa: F401
        return
    except ImportError:
        pass
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_g4f_importable()

# --------------------------------------------------------------------------
# Candidate list
# --------------------------------------------------------------------------

# Text-chat providers worth benchmarking by default (no dedicated media/search
# endpoints, no local-only runtimes). Kept as names so ProviderLoader lazily
# imports only what is actually tested.
DEFAULT_CANDIDATES = [
    "Pollinations",
    "Qwen",
    "ChatGPT",
    "Cloudflare",
    "CopilotApp",
    "DeepInfra",
    "OperaAria",
    "Perplexity",
    "PhindAi",
    "Pi",
    "TeachAnything",
    "Yqcloud",
    "You",
    "GLM",
    "LLM7",
    "OpenRouterFree",
    "Groq",
    "Nvidia",
    "Cerebras",
    "Gemini",
    "GeminiPro",
    "Claude",
    "Grok",
    "DeepSeek",
    "Copilot",
    "HuggingChat",
    "HuggingFace",
    "Puter",
    "KiloCode",
    "OpenCode",
    "Arena",
    "MetaAI",
    "Airforce",
]

# Providers that cannot serve plain chat (media/search/audio/local tooling).
NON_CHAT = {
    "AgentTools",
    "BingCreateImages",
    "BlackForestLabs_Flux1Dev",
    "BlackForestLabs_Flux1KontextDev",
    "BraveSearch",
    "CachedSearch",
    "CohereForAI_C4AI_Command",
    "Custom",
    "DDGS",
    "EdgeTTS",
    "ElevenLabs",
    "GoogleAiMode",
    "GoogleSearch",
    "HailuoAI",
    "Local",
    "MarkItDown",
    "MicrosoftDesigner",
    "OpenAIFM",
    "PollinationsAudio",
    "PollinationsImage",
    "SearXNG",
    "StabilityAI_SD35Large",
    "Video",
    "YouTube",
    "gTTS",
}

# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------

PING_PROMPT = "Reply with exactly one word and nothing else: PONG"

MATH_PROMPT = (
    "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
    "How much does the ball cost? Think briefly, then finish with a line "
    "'ANSWER: <value in dollars>'."
)

JSON_PROMPT = (
    'Return only a JSON object, no markdown fence, with exactly these keys: '
    '"city" (string), "temp_c" (integer), "conditions" (string). '
    "Use Tokyo, 21, cloudy."
)

MULTITURN = [
    {"role": "user", "content": "My name is Aurora and I work on compilers. Remember it."},
    {"role": "assistant", "content": "Noted: your name is Aurora and you work on compilers."},
    {"role": "user", "content": "What is my name and what field do I work in? Answer in one short sentence."},
]

LONGFORM_PROMPT = (
    "Explain the practical difference between TCP and UDP in about 150 words. "
    "Use plain prose, no bullet lists."
)

WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["c", "f"]},
                },
                "required": ["city"],
            },
        },
    }
]

TOOL_PROMPT = (
    "Call the get_weather tool for Tokyo in celsius. "
    "Do not answer from memory, use the tool."
)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class CaseResult:
    name: str
    ok: bool = False
    ms: float = 0.0
    ttft_ms: float = 0.0
    chars: int = 0
    tokens: int = 0
    tok_per_s: float = 0.0
    text: str = ""
    reasoning: bool = False
    tool_called: bool = False
    error: str = ""
    detail: str = ""


@dataclass
class ProviderReport:
    provider: str
    model: str = ""
    needs_auth: bool = False
    native_tools: bool = False
    available: bool = False
    cases: List[CaseResult] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "fail"
    reason: str = ""
    quota: Optional[dict] = None

    def case(self, name: str) -> Optional[CaseResult]:
        for c in self.cases:
            if c.name == name:
                return c
        return None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars/token for latin, ~1.6 for CJK."""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    latin = len(text) - cjk
    return max(1, int(cjk / 1.6 + latin / 4))


def clip(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def classify_error(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc) or ""
    lowered = (name + " " + msg).lower()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in lowered:
        return f"timeout: {clip(msg, 120)}"
    if "missingauth" in lowered or "api key" in lowered or "unauthorized" in lowered:
        return f"auth: {clip(msg, 120)}"
    if "ratelimit" in lowered or "429" in lowered or "rate limit" in lowered:
        return f"rate-limit: {clip(msg, 120)}"
    if "cloudflare" in lowered:
        return f"cloudflare: {clip(msg, 120)}"
    if "ssl" in lowered or "connection" in lowered or "getaddrinfo" in lowered:
        return f"network: {clip(msg, 120)}"
    if "import" in lowered:
        return f"import: {clip(msg, 120)}"
    if isinstance(exc, KeyError):
        return f"not registered: {clip(msg, 120)}"
    return f"{name}: {clip(msg, 140)}"


def score_report(r: ProviderReport, target_ttft: float, target_tps: float) -> None:
    """0-100 agent-suitability score."""
    if not r.available:
        r.score = 0.0
        r.verdict = "fail"
        return

    ping = r.case("ping")
    math = r.case("math")
    js = r.case("json")
    mt = r.case("multiturn")
    long = r.case("longform")
    tool = r.case("tool")

    score = 20.0  # reachable at all

    # instruction following
    score += 10.0 if ping and ping.ok else 0.0
    # reasoning / correctness
    score += 10.0 if math and math.ok else 0.0
    # structured output (agents parse JSON constantly)
    score += 10.0 if js and js.ok else 0.0
    # context retention
    score += 5.0 if mt and mt.ok else 0.0

    # tool calling
    if tool and tool.ok:
        score += 15.0
    elif tool and tool.error:
        score += 0.0
    else:
        score += 3.0  # answered, but did not call the tool

    # latency (TTFT of the ping case)
    ttft = (ping.ttft_ms / 1000.0) if ping and ping.ttft_ms else 99.0
    if ttft <= 0.8:
        score += 15.0
    elif ttft <= 1.5:
        score += 13.0
    elif ttft <= 3.0:
        score += 10.0
    elif ttft <= 5.0:
        score += 6.0
    elif ttft <= 8.0:
        score += 3.0

    # throughput from the long-form case
    tps = long.tok_per_s if long and long.tok_per_s else 0.0
    if tps >= target_tps:
        score += 10.0
    elif tps >= target_tps * 0.6:
        score += 7.0
    elif tps >= target_tps * 0.3:
        score += 4.0
    elif tps > 0:
        score += 2.0

    # stability: any hard error costs points
    hard_errors = sum(1 for c in r.cases if c.error)
    score -= min(10.0, hard_errors * 3.0)

    r.score = round(max(0.0, min(100.0, score)), 1)

    if r.score >= 75 and tool and tool.ok:
        r.verdict = "recommended"
    elif r.score >= 60:
        r.verdict = "usable"
    elif r.score >= 40:
        r.verdict = "marginal"
    else:
        r.verdict = "avoid"


# --------------------------------------------------------------------------
# Provider mode
# --------------------------------------------------------------------------


def load_provider(name: str):
    from g4f.Provider import ProviderUtils

    return ProviderUtils.convert[name]


def provider_models(provider) -> List[str]:
    out: List[str] = []
    default = getattr(provider, "default_model", None)
    if isinstance(default, str) and default and default != "default_model":
        out.append(default)
    aliases = getattr(provider, "model_aliases", None) or {}
    for alias in list(aliases)[:2]:
        if alias not in out:
            out.append(alias)
    out.append("")  # let the provider decide
    return out


def supports_kwarg(func, name: str) -> bool:
    import inspect

    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return True
    return name in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


async def run_provider_case(
    provider,
    model: str,
    messages: List[dict],
    *,
    tools: Optional[list] = None,
    timeout: float = 60.0,
    max_tokens: int = 512,
    name: str = "case",
) -> CaseResult:
    """Run one streamed request against a provider, collecting agent metrics."""
    from g4f.providers.response import Reasoning, ToolCalls, Usage

    func = provider.create_async_generator
    kwargs: Dict[str, Any] = {}
    for key, value in (("stream", True), ("max_tokens", max_tokens), ("timeout", timeout)):
        if supports_kwarg(func, key):
            kwargs[key] = value
    if tools and supports_kwarg(func, "tools"):
        kwargs["tools"] = tools

    result = CaseResult(name=name)
    started = time.perf_counter()
    ttft: Optional[float] = None
    chunks: List[str] = []
    usage_tokens: Optional[int] = None
    tool_names: List[str] = []

    gen = None
    try:
        gen = provider.create_async_generator(model=model, messages=messages, **kwargs)
        while True:
            try:
                chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"no chunk for {timeout:.0f}s")

            if isinstance(chunk, ToolCalls):
                calls = chunk.get_list() or []
                for call in calls:
                    if isinstance(call, dict):
                        tool_names.append(
                            (call.get("function") or {}).get("name")
                            or call.get("name")
                            or "?"
                        )
                if ttft is None:
                    ttft = time.perf_counter() - started
                continue
            if isinstance(chunk, Reasoning):
                result.reasoning = True
                continue
            if isinstance(chunk, Usage):
                data = chunk.get_dict() if hasattr(chunk, "get_dict") else {}
                usage_tokens = (
                    data.get("completion_tokens")
                    or data.get("output_tokens")
                    or data.get("candidatesTokenCount")
                )
                continue
            if not isinstance(chunk, str) or not chunk:
                continue
            if ttft is None:
                ttft = time.perf_counter() - started
            chunks.append(chunk)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:  # noqa: BLE001 - report everything
        result.error = classify_error(exc)
        result.ms = (time.perf_counter() - started) * 1000
        result.detail = clip(str(exc), 200)
    finally:
        if gen is not None and hasattr(gen, "aclose"):
            try:
                await gen.aclose()
            except BaseException:
                pass

    text = "".join(chunks)
    elapsed = time.perf_counter() - started
    result.ms = round(elapsed * 1000, 1)
    result.ttft_ms = round((ttft or 0) * 1000, 1)
    result.text = text
    result.chars = len(text)
    result.tokens = usage_tokens or estimate_tokens(text)
    if elapsed > 0 and result.tokens:
        result.tok_per_s = round(result.tokens / elapsed, 1)
    result.tool_called = bool(tool_names)
    if tool_names:
        result.detail = "tools: " + ", ".join(str(t) for t in tool_names)
    result.ok = bool(text or tool_names)
    return result


def check_ping(r: CaseResult) -> None:
    if r.error:
        return
    word = re.sub(r"[^A-Za-z]", "", r.text).upper()
    r.ok = word == "PONG"
    r.detail = clip(r.text, 80)


def check_math(r: CaseResult) -> None:
    if r.error:
        return
    t = r.text.lower()
    r.ok = bool(re.search(r"0?\.05|\b5\s*(cents|cent)\b", t))
    r.detail = clip(r.text, 120)


def check_json(r: CaseResult) -> None:
    if r.error:
        return
    text = r.text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        r.detail = "no JSON object"
        return
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        r.detail = f"invalid JSON: {exc}"
        return
    r.ok = (
        str(data.get("city", "")).lower().startswith("tokyo")
        and str(data.get("temp_c")) in ("21", "21.0")
        and isinstance(data.get("conditions"), str)
        and bool(data["conditions"])
    )
    r.detail = clip(json.dumps(data, ensure_ascii=False), 100)


def check_multiturn(r: CaseResult) -> None:
    if r.error:
        return
    t = r.text.lower()
    r.ok = "aurora" in t and "compil" in t
    r.detail = clip(r.text, 100)


def check_longform(r: CaseResult) -> None:
    if r.error:
        return
    words = len(re.findall(r"[A-Za-z']+", r.text))
    t = r.text.lower()
    r.ok = words >= 60 and "tcp" in t and "udp" in t
    r.detail = f"{words} words, {clip(r.text, 80)}"


def check_tool(r: CaseResult) -> None:
    if r.error:
        return
    if r.tool_called:
        r.ok = True
        return
    # some providers emit the call as text instead of a structured delta
    t = r.text.lower()
    r.ok = "get_weather" in t and ("tokyo" in t or "city" in t)
    if r.ok:
        r.detail = "text-emitted tool call: " + clip(r.text, 100)


async def bench_provider(name: str, args) -> ProviderReport:
    report = ProviderReport(provider=name)
    try:
        provider = load_provider(name)
    except BaseException as exc:  # noqa: BLE001
        report.reason = classify_error(exc)
        return report

    report.needs_auth = bool(getattr(provider, "needs_auth", False))
    report.native_tools = bool(getattr(provider, "supports_native_tools", False))

    if not getattr(provider, "working", False) and not args.include_unstable:
        report.reason = "provider marked working=False"
        return report
    if report.needs_auth and not args.include_auth:
        report.reason = "needs auth (use --include-auth)"
        return report

    # optional quota probe (cheap, no chat request)
    if args.quota and getattr(provider, "get_quota", None):
        try:
            report.quota = await asyncio.wait_for(
                provider.get_quota(args.api_key), timeout=getattr(args, "quota_timeout", 15)
            )
        except BaseException:
            report.quota = None

    # pick the first model that answers the ping
    model = args.model or ""
    candidates = [model] if model else provider_models(provider)
    ping: Optional[CaseResult] = None
    for candidate in candidates:
        case = await run_provider_case(
            provider,
            candidate,
            [{"role": "user", "content": PING_PROMPT}],
            timeout=args.timeout,
            max_tokens=32,
            name="ping",
        )
        for _ in range(max(0, args.retries)):
            if not case.error:
                break
            await asyncio.sleep(1.5)
            case = await run_provider_case(
                provider,
                candidate,
                [{"role": "user", "content": PING_PROMPT}],
                timeout=args.timeout,
                max_tokens=32,
                name="ping",
            )
        if not case.error:
            ping = case
            model = candidate
            break
        ping = case  # remember the last failure for the report
    if ping is None:
        report.reason = "no model produced a response"
        return report

    check_ping(ping)
    if ping.error and not report.reason:
        report.reason = ping.error
    report.model = model
    report.cases.append(ping)
    report.available = not ping.error and (ping.chars > 0 or ping.tool_called)

    if not report.available and not args.force:
        score_report(report, args.target_ttft, args.target_tps)
        return report

    case_specs = [
        ("math", [{"role": "user", "content": MATH_PROMPT}], None, check_math, 256),
        ("json", [{"role": "user", "content": JSON_PROMPT}], None, check_json, 160),
        ("multiturn", MULTITURN, None, check_multiturn, 160),
        ("longform", [{"role": "user", "content": LONGFORM_PROMPT}], None, check_longform, 400),
    ]
    if args.tool_test:
        case_specs.append(
            ("tool", [{"role": "user", "content": TOOL_PROMPT}], WEATHER_TOOL, check_tool, 160)
        )

    for case_name, messages, tools, checker, max_tokens in case_specs:
        if args.case and case_name not in args.case:
            continue
        case = await run_provider_case(
            provider,
            model,
            messages,
            tools=tools,
            timeout=args.timeout,
            max_tokens=max_tokens,
            name=case_name,
        )
        checker(case)
        report.cases.append(case)

    score_report(report, args.target_ttft, args.target_tps)
    if not report.reason:
        failed = [c.name for c in report.cases if not c.ok]
        report.reason = "failed cases: " + ", ".join(failed) if failed else "all cases passed"
    return report


# --------------------------------------------------------------------------
# Endpoint mode (OpenAI-compatible server, e.g. the g4f API)
# --------------------------------------------------------------------------


async def run_endpoint_case(
    base_url: str,
    model: str,
    messages: List[dict],
    *,
    api_key: str = "",
    tools: Optional[list] = None,
    timeout: float = 60.0,
    max_tokens: int = 512,
    name: str = "case",
) -> CaseResult:
    import aiohttp

    url = base_url.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    result = CaseResult(name=name)
    started = time.perf_counter()
    ttft: Optional[float] = None
    chunks: List[str] = []
    usage_tokens: Optional[int] = None
    tool_names: List[str] = []

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout, sock_read=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(f"HTTP {resp.status}: {clip(body, 160)}")
                async for raw in resp.content:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event.get("usage"):
                        usage_tokens = event["usage"].get("completion_tokens") or usage_tokens
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("tool_calls"):
                            for call in delta["tool_calls"]:
                                fn = call.get("function") or {}
                                if fn.get("name"):
                                    tool_names.append(fn["name"])
                            if ttft is None:
                                ttft = time.perf_counter() - started
                        content = delta.get("content")
                        if content:
                            if ttft is None:
                                ttft = time.perf_counter() - started
                            chunks.append(content)
                        if delta.get("reasoning_content"):
                            result.reasoning = True
    except BaseException as exc:  # noqa: BLE001
        result.error = classify_error(exc)
        result.detail = clip(str(exc), 200)

    text = "".join(chunks)
    elapsed = time.perf_counter() - started
    result.ms = round(elapsed * 1000, 1)
    result.ttft_ms = round((ttft or 0) * 1000, 1)
    result.text = text
    result.chars = len(text)
    result.tokens = usage_tokens or estimate_tokens(text)
    if elapsed > 0 and result.tokens:
        result.tok_per_s = round(result.tokens / elapsed, 1)
    result.tool_called = bool(tool_names)
    if tool_names:
        result.detail = "tools: " + ", ".join(sorted(set(tool_names)))
    result.ok = bool(text or tool_names)
    return result


async def bench_endpoint(model: str, args) -> ProviderReport:
    report = ProviderReport(provider=args.base_url, model=model)

    ping = await run_endpoint_case(
        args.base_url,
        model,
        [{"role": "user", "content": PING_PROMPT}],
        api_key=args.api_key,
        timeout=args.timeout,
        max_tokens=32,
        name="ping",
    )
    check_ping(ping)
    report.cases.append(ping)
    report.available = not ping.error and (ping.chars > 0 or ping.tool_called)
    if ping.error:
        report.reason = ping.error
    if not report.available:
        score_report(report, args.target_ttft, args.target_tps)
        return report

    specs = [
        ("math", [{"role": "user", "content": MATH_PROMPT}], None, check_math, 256),
        ("json", [{"role": "user", "content": JSON_PROMPT}], None, check_json, 160),
        ("multiturn", MULTITURN, None, check_multiturn, 160),
        ("longform", [{"role": "user", "content": LONGFORM_PROMPT}], None, check_longform, 400),
    ]
    if args.tool_test:
        specs.append(
            ("tool", [{"role": "user", "content": TOOL_PROMPT}], WEATHER_TOOL, check_tool, 160)
        )
    for case_name, messages, tools, checker, max_tokens in specs:
        if args.case and case_name not in args.case:
            continue
        case = await run_endpoint_case(
            args.base_url,
            model,
            messages,
            api_key=args.api_key,
            tools=tools,
            timeout=args.timeout,
            max_tokens=max_tokens,
            name=case_name,
        )
        checker(case)
        report.cases.append(case)

    score_report(report, args.target_ttft, args.target_tps)
    report.reason = report.reason or "ok"
    return report


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def fmt_ms(ms: float) -> str:
    if not ms:
        return "—"
    return f"{ms/1000:.2f}s"


def print_table(reports: List[ProviderReport], show_details: bool) -> None:
    header = (
        f"{'provider':26s} {'score':>5s} {'verdict':11s} {'ttft':>7s} {'tok/s':>6s} "
        f"{'ping':4s} {'math':4s} {'json':4s} {'mt':4s} {'tool':5s} note"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in sorted(reports, key=lambda x: (-x.score, x.provider)):
        ping = r.case("ping")
        marks = []
        for name in ("math", "json", "multiturn", "tool"):
            c = r.case(name)
            marks.append("✓" if c and c.ok else ("✗" if c else "·"))
        ping_mark = "✓" if ping and ping.ok else ("✗" if ping else "·")
        ttft = fmt_ms(ping.ttft_ms if ping else 0)
        tps = r.case("longform").tok_per_s if r.case("longform") else 0
        print(
            f"{clip(r.provider, 26):26s} {r.score:5.1f} {r.verdict:11s} {ttft:>7s} "
            f"{(f'{tps:.1f}' if tps else '—'):>6s} {ping_mark:4s} "
            f"{marks[0]:4s} {marks[1]:4s} {marks[2]:4s} {marks[3]:5s} {clip(r.reason, 40)}"
        )
        if show_details:
            for c in r.cases:
                if c.text or c.error:
                    status = "ok" if c.ok else ("error" if c.error else "fail")
                    print(
                        f"    - {c.name:10s} {status:5s} {fmt_ms(c.ms):>7s} "
                        f"{c.tok_per_s:5.1f} t/s  {c.detail or c.error or clip(c.text, 90)}"
                    )


def write_markdown(reports: List[ProviderReport], path: str, args) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# g4f provider benchmark",
        "",
        f"- run: {stamp}",
        f"- mode: {'endpoint ' + args.base_url if args.base_url else 'providers'}",
        f"- cases per provider: ping, math, json, multiturn, longform"
        + (", tool" if args.tool_test else ""),
        f"- per-request timeout: {args.timeout:.0f}s",
        "",
        "| provider | model | score | verdict | TTFT | tok/s | ping | math | json | multi-turn | tools | note |",
        "|---|---|---:|---|---:|---:|:--:|:--:|:--:|:--:|:--:|---|",
    ]
    for r in sorted(reports, key=lambda x: (-x.score, x.provider)):
        ping = r.case("ping")
        marks = []
        for name in ("math", "json", "multiturn", "tool"):
            c = r.case(name)
            marks.append("✓" if c and c.ok else ("✗" if c else "—"))
        tps = r.case("longform").tok_per_s if r.case("longform") else 0
        lines.append(
            f"| {r.provider} | {r.model or '—'} | {r.score:.1f} | {r.verdict} | "
            f"{fmt_ms(ping.ttft_ms if ping else 0)} | "
            f"{f'{tps:.1f}' if tps else '—'} | "
            f"{'✓' if ping and ping.ok else '✗'} | {' | '.join(marks)} | "
            f"{r.reason.replace('|', '/')} |"
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nmarkdown report written to {path}")


def write_json(reports: List[ProviderReport], path: str, args) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "endpoint" if args.base_url else "providers",
        "base_url": args.base_url,
        "timeout": args.timeout,
        "reports": [asdict(r) for r in reports],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    print(f"json report written to {path}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Benchmark g4f providers or an OpenAI-compatible endpoint for agent use.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--providers", help="comma separated provider names")
    p.add_argument("--all-public", action="store_true", help="test every working provider without auth")
    p.add_argument("--all", action="store_true", help="test every registered chat provider")
    p.add_argument("--include-auth", action="store_true", help="include needs_auth providers (cookies/keys required)")
    p.add_argument("--include-unstable", action="store_true", help="include providers marked working=False")
    p.add_argument("--model", default="", help="force one model instead of auto-picking")
    p.add_argument("--case", action="append", help="restrict to a case name (ping/math/json/multiturn/longform/tool)")
    p.add_argument("--no-tool-test", dest="tool_test", action="store_false", help="skip the tool-calling case")
    p.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds")
    p.add_argument("--retries", type=int, default=1, help="retries for the availability ping")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--concurrency", type=int, default=3, help="providers tested in parallel")
    p.add_argument("--target-ttft", type=float, default=1.5, help="target seconds to first token")
    p.add_argument("--target-tps", type=float, default=40.0, help="target output tokens per second")
    p.add_argument("--quota", action="store_true", help="also probe provider quota endpoints")
    p.add_argument("--force", action="store_true", help="run remaining cases even if ping failed")
    p.add_argument("--json", dest="json_path", help="write machine-readable JSON results")
    p.add_argument("--md", dest="md_path", help="write a markdown report")
    p.add_argument("--details", action="store_true", help="print per-case detail")
    p.add_argument("--quick", action="store_true", help="only ping + tool call (fast triage)")
    p.add_argument("--list", action="store_true", help="list candidate providers and exit")
    p.add_argument("--base-url", default="", help="benchmark an OpenAI-compatible endpoint instead, e.g. http://127.0.0.1:8080/v1")
    p.add_argument("--api-key", default=os.environ.get("G4F_API_KEY", ""), help="API key for endpoint mode")
    p.add_argument("--models", default="auto", help="comma separated models for endpoint mode")
    return p.parse_args(argv)


def resolve_provider_names(args) -> List[str]:
    if args.providers:
        return [x.strip() for x in args.providers.split(",") if x.strip()]
    if not (args.all or args.all_public):
        return list(DEFAULT_CANDIDATES)

    from g4f.Provider import ProviderLoader

    names = [n for n in ProviderLoader.names if n not in NON_CHAT]
    if args.all_public:
        keep = []
        for name in names:
            try:
                provider = load_provider(name)
            except BaseException:
                continue
            if getattr(provider, "working", False) and not getattr(provider, "needs_auth", False):
                keep.append(name)
        return keep
    return names


async def main_async(args) -> int:
    if args.list:
        names = resolve_provider_names(args)
        print(f"{len(names)} candidate providers:\n")
        for name in names:
            try:
                provider = load_provider(name)
                print(
                    f"  {name:28s} working={str(getattr(provider,'working',False)):5s} "
                    f"auth={str(getattr(provider,'needs_auth',False)):5s} "
                    f"native_tools={str(getattr(provider,'supports_native_tools',False)):5s} "
                    f"default={getattr(provider,'default_model','') or '—'}"
                )
            except BaseException as exc:  # noqa: BLE001
                print(f"  {name:28s} <unavailable: {classify_error(exc)}>")
        return 0

    if args.base_url:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        reports = [await bench_endpoint(model, args) for model in models]
    else:
        names = resolve_provider_names(args)
        sem = asyncio.Semaphore(max(1, args.concurrency))

        async def guarded(name: str) -> ProviderReport:
            async with sem:
                print(f"… testing {name}", file=sys.stderr, flush=True)
                try:
                    return await bench_provider(name, args)
                except BaseException as exc:  # noqa: BLE001
                    report = ProviderReport(provider=name, reason=classify_error(exc))
                    return report

        reports = await asyncio.gather(*(guarded(name) for name in names))

    if args.quick:
        # Triage mode only measures reachability + tool calling; do not pretend
        # the full 0-100 scale applies.
        for r in reports:
            if r.available:
                tool = r.case("tool")
                r.verdict = "candidate" if tool and tool.ok else "candidate-no-tools"

    print_table(reports, args.details)

    reachable = [r for r in reports if r.available]
    print(
        f"\n{len(reachable)}/{len(reports)} providers answered. "
        f"recommended: {', '.join(r.provider for r in reports if r.verdict=='recommended') or '—'}"
    )
    if args.md_path:
        write_markdown(reports, args.md_path, args)
    if args.json_path:
        write_json(reports, args.json_path, args)
    return 0 if reachable else 2


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.quick:
        args.tool_test = True
        args.case = ["ping", "tool"]
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
