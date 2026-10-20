# 供应商实测与 Agent 可用性评估

> 目标：只保留 g4f 的 **反向代理（OpenAI 兼容 API）** 能力时，找出真正可用、速度与质量适合 Agent 循环的上游供应商。
>
> 社区每日实测的结论见 **[community-provider-eval-2026-10.md](community-provider-eval-2026-10.md)**（2026-10-20 更新）：
> 免 key 首选 `KiloCode` / `LLM7`，`Pollinations` 免费层已于 2026-07 终止。

## 0. 本次结论的可信边界

本次分析在 Arena 沙箱中完成，沙箱出网有白名单，**只允许 github.com / pypi.org / registry.npmjs.org**。
所有上游（pollinations.ai、chat.qwen.ai、gemini.google.com…）的 TLS 连接都会被立即关闭：

```
Gemini        network: Cannot connect to host gemini...
Pollinations  network: HTTPSConnectionPool(host='image.pollinations.ai'...)
Qwen          network: Failed to perform, curl: (35) ...
```

因此这里**不提供任何编造的延迟/质量数字**。已经交付的是：

1. 一个可直接跑的基准脚本 `scripts/bench_providers.py`（6 项测试 + 打分 + Markdown/JSON 报告）；
2. 基于代码元数据的供应商分层和优先测试顺序；
3. 一套面向 Agent 的反向代理配置建议。

在你能出网的机器上执行 10 分钟，就能得到属于你所在地区/出口 IP 的真实排名。

---

## 1. 一键实测

```bash
# 0) 依赖（最小即可，基准脚本只用 aiohttp / g4f 本身）
pip install -r requirements.txt

# 1) 看候选与静态标记
python scripts/bench_providers.py --list

# 2) 快速排查：只测「能不能答」+「会不会调用工具」，约 2 分钟
#    （此模式只给 candidate / candidate-no-tools，不给 0-100 分）
python scripts/bench_providers.py --all-public --concurrency 6 --timeout 45 --quick

# 3) 完整评估：ping / 数学 / JSON / 多轮 / 长文速度 / 工具调用
python scripts/bench_providers.py --all-public --concurrency 3 --timeout 60 \
    --md report.md --json report.json --details

# 4) 单通道速查（仓库自带的 CLI 子命令，只发一次 hello）
g4f test Pollinations

# 5) 带上需要 cookie / key 的通道（先在 ~/.g4f/cookies 放好 cookie 或用 login）
python scripts/bench_providers.py --providers Gemini,Copilot,Grok,Puter --include-auth
```

脚本也可以直接压测你已经部署好的反代服务：

```bash
python scripts/bench_providers.py --base-url http://127.0.0.1:8080/v1 \
    --api-key "$G4F_API_KEY" --models auto,openai,agent-primary
```

脚本本身已用本地 OpenAI 兼容 mock 服务逐项验证（流式、tool_calls、usage、
超时、非 200 响应均覆盖）。输出示例：

```
provider                   score verdict        ttft  tok/s ping math json mt   tool  note
http://127.0.0.1:8099/v1    95.0 recommended   0.35s  162.9 ✓    ✓    ✓    ✓    ✓     ok
```

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 至少一个通道可用 |
| 2 | 全部失败（通常是没有网络出口） |
| 130 | 手动中断 |

---

## 2. 评分口径（0–100）

| 维度 | 分值 | 判定 |
|---|---:|---|
| 可达性 | 20 | 能建连并返回内容 |
| 指令遵循 | 10 | `Reply with exactly: PONG` 严格匹配 |
| 推理正确 | 10 | 球拍/球问题必须答 `0.05` |
| 结构化输出 | 10 | 只返回合法 JSON 且字段正确 |
| 多轮记忆 | 5 | 两轮后仍记得姓名与领域 |
| 工具调用 | 15 | 发出 `get_weather(city="Tokyo")` 的 tool call |
| 首字延迟 TTFT | 15 | ≤0.8s 满分，>8s 为 0 |
| 输出吞吐 | 10 | ≥40 tok/s 满分，按比例递减 |
| 稳定性 | 扣分 | 每出现一次硬错误 −3，最多 −10 |

判定：

- `recommended`：score ≥ 75 **且** 工具调用通过
- `usable`：score ≥ 60
- `marginal`：score ≥ 40
- `avoid`：其余

> Agent 一般标准（本脚本的默认阈值）：**TTFT < 1.5s、≥ 40 tok/s、能稳定产出 tool_calls、JSON 不失真**。
> 长文任务可放宽到 TTFT < 3s；多步工具链建议 TTFT < 1s。

`tok/s` 优先使用上游返回的 `usage`，没有时按字符估算（CJK 1.6 字/token，拉丁 4 字符/token）。

---

## 3. 供应商分层（静态元数据）

仓库当前注册 **65 个供应商**（144 个 `.py`），其中：

- `working=True` 且免登录：**35 个**
- `working=True` 但需要 cookie/key：**15 个**
- 明确标记 `working=False`：8 个（如 `DeepSeek`、`QwenCode`、`SearXNG`）

### 3.1 免登录 + OpenAI 协议 + 原生 tools（优先测这批）

这些是 `OpenaiTemplate` 子类或显式声明 `supports_native_tools=True`，最符合 Agent 需要：

| 供应商 | 上游 | 备注 |
|---|---|---|
| `Pollinations` | gen.pollinations.ai | ⚠️ 免费层 2026-07 终止，需 key；旧匿名文本域仍可用但不稳定 |
| `DeepInfra` | api.deepinfra.com | OpenAI 兼容；无 key 时走网页兜底（可能需要浏览器） |
| `Groq` | api.groq.com | 无 key 时回落 `g4f.space/api/groq` |
| `Nvidia` | integrate.api.nvidia.com | 回落 `nvidia.g4f.dev` |
| `Cerebras` | api.cerebras.ai | 有匿名 demoApiKey 逻辑 |
| `GeminiPro` | generativelanguage.googleapis.com | 无 key 时回落 `g4f.space/api/gemini` |
| `OpenRouterFree` | openrouter.ai | 回落 `open.g4f.dev` |
| `LLM7` / `KiloCode` / `OpenCode` / `Airforce` / `You` | 各自网关 | `active_by_default=True` |
| `HuggingFace` | router.huggingface.co | 需要 token，但协议标准 |

> 这一组的共同点：**协议稳定、支持流式与 tools**，失效时多数还有 `backup_url` 兜底。
> 但“无 key 可用”通常意味着请求实际经过 `g4f.space` / `g4f.dev`，多一跳，延迟和可用性取决于该公共服务。

### 3.2 网页逆向类（能用，但不要作为主通道）

`Qwen`、`ChatGPT`、`GLM`、`Gemini`、`Perplexity`、`CopilotApp`、`OperaAria`、`Pi`、`Yqcloud`、`TeachAnything`、`Cloudflare`、`MetaAI`、`Arena`。

- 多数**没有原生 tools**，g4f 会用 `ToolSupportProvider` 做**提示词模拟**（一次请求变两次，TTFT 和成本上升）；
- 依赖站点前端接口，改版即失效；
- 部分实现会启动浏览器（`Cloudflare`、`Qwen`、`Arena`、`Pi`、`ChatGPT`、`GLM`、`Gemini`、`Copilot`、`HuggingChat` 等）。

实测时的典型报错就是 `Google Chrome / Chromium not found` —— 服务器上要么装 Chrome，要么用
`g4f-go browser install`（Lightpanda），或者干脆只用 3.1 的纯 HTTP 通道。

### 3.3 需要登录/密钥（质量最好，维护成本也最高）

`Antigravity`、`GeminiCLI`、`Copilot`、`GithubCopilot`、`Grok`、`Puter`、`HuggingChat`、`DeepSeek`(暂停)、`BlackboxPro`、`MetaAIAccount`、`HailuoAI`、`WhiteRabbitNeo`。

- 需要 `~/.g4f/cookies` 下的 cookie/HAR，或 `*_API_KEY` 环境变量；
- 容器里通常通过 `:7900` 的桌面手动登录一次；
- 质量、tools、上下文长度最接近官方，适合作为 **主通道**，免费通道作为 fallback。

### 3.4 不适合作为 Agent 通道

`PollinationsImage`、`PollinationsAudio`、`BingCreateImages`、`MicrosoftDesigner`、`BlackForestLabs_*`、`StabilityAI_SD35Large`、`CohereForAI_C4AI_Command`（HF Space 图像）、`BraveSearch`、`GoogleSearch`、`GoogleAiMode`、`CachedSearch`、`YouTube`、`Video`、`EdgeTTS`、`gTTS`、`ElevenLabs`、`OpenAIFM`、`MarkItDown`、`Local`。

它们是工具/媒体通道，可以挂在同一套 API 上，但不参与对话路由。

---

## 4. 建议的测试顺序

### 4.0 优先测试清单（按“Agent 适配度”排序）

| 顺序 | 供应商 | 社区实测（2026-10-19） | 需要 key/cookie |
|---:|---|---|:--:|
| 1 | `KiloCode` | 10 个免费模型，0.5–3.8s，原生 tools，200 次/小时/IP | 否 |
| 2 | `LLM7` | 1.0s，匿名，原生 tools，约 100 万 token/天 | 否 |
| 3 | `Perplexity` | 19 个模型（Claude/GPT/Grok），~3.5s，但会 429、无原生 tools | 否 |
| 4 | `Cloudflare` | 49 个模型，12–40s，极稳但只适合兜底 | 否 |
| 5 | `GeminiPro` | 社区公认最稳，原生 tools | 是（AI Studio key） |
| 6 | `Groq` | 延迟最低，30 RPM / 1K RPD | 是 |
| 7 | `Nvidia` / `OpenRouterFree` | 额度大 / 免费模型质量最高 | 是 |
| 8 | `Gemini` / `Copilot` / `Grok` / `Puter` | 质量上限高，但需登录；Puter 当前 1,041 条错误 | 是 |

免 key 先用 1–4 建主备；能加 key 就把 5–6 提到主通道。
`Pollinations` 已从首选移除：免费层 2026-07 终止，详见社区评估文档。


1. **第一轮（10 分钟）**：`--all-public --quick`
   目标：筛出“当前网络下真的能回话”的名单。
2. **第二轮（20 分钟）**：对第一轮 `ping` 通过的通道跑完整 6 项。
   关注 `tool` 列和 `longform` 的 tok/s。
3. **第三轮（稳定性）**：同一天不同时段跑 3 次，记录成功率。
   免费通道的可用性波动通常大于速度差异。
4. **决定主备**：`recommended` 里选 2 个不同上游做 `config.yaml` 主备，另加 1 个需要 key 的高质量通道。

建议长期挂一个每日 cron：

```bash
0 6 * * * cd /opt/gpt4free && .venv/bin/python scripts/bench_providers.py \
  --all-public --quick --timeout 40 --json /var/log/g4f/bench-$(date +\%F).json
```

---

## 5. 只保留反代 API 的部署

### 5.1 启动

```bash
# 不挂 Web GUI，只开 OpenAI 兼容 API
python -m g4f --no-gui --bind 0.0.0.0 --port 8080

# 等价 CLI
g4f api --no-gui --port 8080 --debug
```

关键环境变量（`.env` 或容器 env）：

```dotenv
G4F_API_KEY=<随机长字符串>       # 打开鉴权；不设就是完全公开
G4F_TIMEOUT=600
G4F_STREAM_TIMEOUT=600
G4F_PROXY=                       # 需要统一出口时填
G4F_CORS_ORIGINS=https://your.app
G4F_IGNORED_PROVIDERS=Local,MarkItDown
G4F_BROWSER_HOST=127.0.0.1
G4F_BROWSER_PORT=9222            # 指向 Lightpanda / Chrome 的 CDP
```

### 5.2 多级 fallback（`~/.g4f/cookies/config.yaml`）

```yaml
models:
  - name: "agent-primary"
    providers:
      - provider: "Pollinations"
        model: "openai"
      - provider: "GeminiPro"
        model: "gemini-2.5-flash"
        condition: "error_count < 3"
      - provider: "Groq"
        model: "llama-3.3-70b-versatile"
      - provider: "OpenRouterFree"
        model: "auto"

  - name: "agent-fast"
    providers:
      - provider: "Cerebras"
        model: "llama-3.3-70b"
      - provider: "Nvidia"
        model: "meta/llama-3.3-70b-instruct"
      - provider: "Pollinations"
        model: "openai-fast"
```

条件表达式只允许 `quota.*`、`balance`、`error_count` 和比较/布尔运算，不会执行任意 Python。

### 5.3 客户端

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1
export OPENAI_API_KEY=$G4F_API_KEY
```

```python
from openai import OpenAI
c = OpenAI()
r = c.chat.completions.create(
    model="agent-primary",
    messages=[{"role": "user", "content": "hi"}],
    stream=True,
    tools=[{"type": "function", "function": {
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }}],
)
```

### 5.4 Nginx 反代（SSE 必须关缓冲）

```nginx
location /v1/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    proxy_buffering off;          # 否则流式会被整段缓存
    proxy_read_timeout 600s;
    client_max_body_size 50m;
}
```

### 5.5 观测

| 端点 | 用途 |
|---|---|
| `GET /v1/models` | 当前可用模型/供应商（带缓存） |
| `GET /api/{provider}/health` | 只发 GET，不消耗对话额度 |
| `GET /api/{provider}/quota` | 余额/配额（需供应商实现） |
| `GET /api/logs`、`/logs` | 运行日志 |
| `G4F_ENABLE_AUDIT_LOG=1` | 落 HAR 审计，便于排查上游失败 |

---

## 6. 结果记录模板

跑完把 `report.md` 的内容贴到下面，或直接看脚本生成的表：

| 排名 | provider | model | score | TTFT | tok/s | tools | 备注 |
|---:|---|---|---:|---:|---:|:--:|---|
|  |  |  |  |  |  |  |  |

---

## 7. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 大面积 `network: ... SSL ...` | 出口被墙或被代理拦截；设置 `G4F_PROXY` 或换网络 |
| `Google Chrome / Chromium not found` | 该供应商需要浏览器；装 Chrome、`g4f-go browser install`，或用纯 HTTP 通道 |
| `auth: ... cookie not found` | 该供应商实际需要 cookie/key，`needs_auth` 元数据可能滞后 |
| 工具调用列是 `✗` 但对话正常 | 无原生 tools；API 层会用提示词模拟，能出 `tool_calls` 但多一次请求 |
| TTFT 很高但 tok/s 正常 | 上游排队或提示词模拟导致；优先换主通道 |
| 免费通道今天能跑明天挂 | 正常现象；用 `config.yaml` 多级 fallback + 每日基准 |

---

## 8. 合规提醒

这些通道大多不是官方公开 API。上线前请确认目标站点条款、当地法律与 `LEGAL_NOTICE.md`；
不要把无鉴权的反代直接暴露在公网。
