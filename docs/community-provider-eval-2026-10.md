# 社区实测评估：哪些供应商适合「反代 API + Agent」（2026-10）

> 数据截止 **2026-10-20**。本文只回答一个问题：把 g4f 当作反向代理（OpenAI 兼容 `/v1`）时，上游选谁。
> 配套工具：`scripts/bench_providers.py`；方法论见 [provider-agent-benchmark.md](provider-agent-benchmark.md)。

---

## 0. 一句话结论

**免 key 场景下，社区每日实测里真正能跑、又快到能进 Agent 循环的只有三个：`KiloCode`、`LLM7`、`Perplexity`。**
`Cloudflare` 很稳但 12–40 秒，只能兜底；`Pollinations` 免费 Pollen 已取消、g4f 走的文本端点实测全挂，别再当主力；`Puter`/`Airforce`/`OpenaiChat`/`Qwen` 网页版当前基本不可用。
愿意加一个免费 key 的话，`GeminiPro`（AI Studio）和 `Groq` 是社区公认的稳定/最快选择。

---

## 1. 证据来源

| 来源 | 时间 | 内容 |
|---|---|---|
| [Free-AI-Things/g4f-working](https://github.com/Free-AI-Things/g4f-working) | 每日自动跑，最新 2026-10-19 | 用 GitHub Actions 起 g4f API，实测 **68 个供应商 / 4,391 个 provider-model 组合** |
| [g4f v8.8.0](https://github.com/xtekky/gpt4free/releases/tag/v8.8.0) | 2026-10-19 | 当前版本；修复了工具调用格式 |
| [g4f.dev #70](https://github.com/gpt4free/g4f.dev/issues/70) / [#3527](https://github.com/xtekky/gpt4free/issues/3527) | 2026-03 / 2026-09 | `tool_calls` 缺 `index`、`arguments` 非字符串 → opencode 报 `AI_TypeValidationError` |
| [g4f.dev ready_to_use](https://g4f.dev/docs/ready_to_use.html) | 持续更新 | 官方免 key 网关：`g4f.space/api/{groq,ollama,pollinations,nvidia,gemini}` |
| [ClawLabsAI/free-ai-models](https://github.com/ClawLabsAI/free-ai-models) | 每日，最新 2026-10-19 | 免费模型质量分、tools 支持、是否拿你的 prompt 训练 |
| [Pollinations 免费层终止](https://agentdeals.dev/vendor/pollinations-ai) | 2026-07-10 | 免费 Pollen 取消，文档 API 需 key |
| [Pollinations #17776](https://github.com/pollinations/pollinations/issues/17776) | 2026-10-17 | 匿名图像限速：每 IP 每 45 秒 1 张 |
| [Free LLM API Tiers 2026-10](https://dev.to/tariqnasser/free-llm-api-tiers-in-october-2026-whats-left-and-how-i-chain-them-227l) | 2026-10-06 | Kilo 200 次/小时/IP；OpenRouter 20 RPM/50 RPD；Groq 30 RPM/1K RPD |
| [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) | 2026-10-13 | 免费池清单与坑 |
| [LINUX DO 反代讨论](https://linux.do/t/topic/1638550) | 2026-02 | “稳定只有 Google AI Studio；Kiro / Antigravity 上午用下午封” |

---

## 2. 每日实测原始结果（2026-10-19）

```
总测试组合: 4391
可用:       115 (2.62%)
平均响应:   11.02s
可用媒体:   image 0 / audio 0 / video 0
```

按供应商拆开（响应时间包含 g4f 自身开销与测试端 50 并发排队，**绝对值偏悲观，看相对值**）：

| 供应商 | 可用模型数 | 最快 | 中位 | 最慢 | 备注 |
|---|---:|---:|---:|---:|---|
| `Cloudflare` | 49 | 12.1s | 21.8s | 39.5s | 静态模型多，稳但**太慢**；需 CDP 浏览器过校验 |
| `Perplexity` | 19 | 3.41s | 3.56s | 3.73s | Claude/GPT/Grok 免费网页版；26 次 429 |
| `OpenAIFM` | 17 | 0.09s | 0.69s | 0.69s | 纯 TTS，不参与对话 |
| **`KiloCode`** | **10** | **0.52s** | **1.13s** | **3.84s** | 免 key，OpenAI 协议 |
| `HuggingSpace` | 7 | 0.55s | 0.81s | 3.16s | Command 系列 |
| `CohereForAI_C4AI_Command` | 4 | 0.85s | 0.88s | 0.98s | 同上 |
| **`LLM7`** | **1** | 1.01s | 1.01s | 1.01s | 免 key |
| `Pollinations` | **1**（sana 图像） | 0.70s | — | — | 216 条文本请求全失败 |
| `Gemini`（网页版） | 1 | 1.56s | — | — | 需 cookie/浏览器 |
| `Yqcloud` | 1 | 3.04s | — | — | 低质量克隆 |
| `Qwen`（网页版） | 1 | 8.43s | — | — | 42 次 HTTP 500 |
| `AgentTools` | 1 | 21.46s | — | — | 自家 MCP Agent，慢 |

失败分布（共 4,276 条，其中 429 占 667 条 —— 免费通道的限流比报错更常见）：

| 错误 | 数量 | 主要来源 |
|---|---:|---|
| `MissingAuthError` | 2,039 | `Puter` 1,028、`Airforce` 798、`HuggingFaceMedia` 662 |
| `Request timeout` | 275 | 集中在慢供应商 |
| `HTTP 500 Request execution failed` | 1,263 | `Pollinations` 216、`Nvidia` 83、`GeminiPro` 75、`Qwen` 42、`OpenRouterFree` 15、`Groq` 11 |
| `HTTP 429` | 667 | 各免费通道限流；`Perplexity` 单独占 26 条 |

> 测试口径：单条 prompt「Hello, are you working? Reply with 'Yes'」，120s 超时，50 并发，单 GitHub runner IP。
> 它测的是**可用性**，不是质量；质量看第 4 节。

---

## 3. 关键事实：为什么结论和直觉不一样

### 3.1 Pollinations 的免费时代结束了

- 2026-07-10 起取消免费 Pollen（社区记录），文档 API（`gen.pollinations.ai`）**需要 key**：无 key 401，额度耗尽 402。
- 也有社区记录称旧文本域 `text.pollinations.ai` 对匿名请求仍可用（约 1 次/15 秒）；但 g4f 的 `Pollinations` 走新域名 + `g4f.space` 备份，2026-10-19 实测 216 条文本请求全 500。
- 匿名图像仍可用，但限到 **1 张 / 45 秒 / IP**。
- 结论：**不要再把 Pollinations 当免 key 主力**，它现在是「有 key 才正常」的通道。

### 3.2 KiloCode 是当前最好的免 key 网关

g4f 里的 `KiloCode` 实际指向 `https://api.kilo.ai/api/gateway`，默认 `kilo-auto/free`，无需 key。10 个可用模型，中位 1.1 秒，其中包括：

```
kilo-auto/small
openrouter/free
nvidia/nemotron-3-ultra-550b-a55b:free
nvidia/nemotron-3.5-super-vl:free
minimax/minimax-m3.1-flash:free
poolside/laguna-s-2.1:free
cohere/north-mini-code:free
dots-studio/dots-3-note-preview:free
liquid/lfm-2.5-2.6b:free
reflection/beam-free
```

- 协议是标准 OpenAI Chat Completions，**原生 tools**；
- 社区口径的硬限制：**200 请求/小时/IP**，超了 429；
- 免费池会变，`/api/gateway/models` 目录可能滞后于实际可服务的模型。

### 3.3 LLM7：匿名、1 秒、够小够快

- `https://api.llm7.io/v1`，`default` 模型，无需 key；
- 社区报告：匿名可用；注册免费 token 后约 **100 万 token/天**；
- 原生 tools，适合当「Kilo 被限流后的第一备胎」。

### 3.4 Perplexity：质量最高的免费网页通道，但会 429

- 19 个模型，含 `claude45sonnet`、`gpt5_thinking`、`grok`、`o3pro`；
- 响应稳定在 3.5 秒左右；
- **没有原生 tools**，g4f 会走提示词模拟（一次变两次请求，TTFT 翻倍）；
- 网页逆向，风控/改版即失效，26 次 429 说明并发一大就顶不住。

### 3.5 Cloudflare：稳定但只能兜底

49 个模型可用，包含 `glm-5.2`、`gpt-oss-120b`、`llama-3.3-70b`、`qwen-2.5-coder-32b`；
但 12–40 秒的响应对 Agent 循环是灾难，且 provider 内部会走 CDP 浏览器过 Cloudflare 校验。
适合「其它全挂了我还要有输出」的最后一级，部署时要装 Chrome / Lightpanda。

### 3.6 需要 key 的通道：社区口碑最好

| 供应商 | 免费额度（社区口径） | 为什么值得 |
|---|---|---|
| `GeminiPro`（AI Studio） | 免费层仍在，额度不公开 | 国内社区公认「最稳」；原生 tools；`g4f.space/api/gemini` 可兜底 |
| `Groq` | 30 RPM / 1,000 RPD / 8K TPM | 延迟最低，适合多步工具链 |
| `NVIDIA NIM` | 40 RPM / 10,000 RPD | 额度大，但条款是 evaluation-only |
| `OpenRouter :free` | 20 RPM / 50 RPD（充值 $10 后 1,000 RPD） | 免费池质量最高：`nemotron-3-ultra` 65.8、`gemma-4-31b` 57.1、`inkling` 67.6，且都支持 tools |

> `g4f.space/api/{groq,nvidia,gemini}` 官方标注「none required」，但 2026-10-19 的实测里这些通道大量 500。
> 说明公共网关不能当作 SLA，要么自己配 key，要么接受它随时抽风。

### 3.7 明确不要用的

| 供应商 | 证据 |
|---|---|
| `Puter` | 1,041 条错误（其中 1,028 条 401）；且历史上 `tool_calls` 格式错误（#3527） |
| `Airforce` | 798 条失败 |
| `Pollinations` | 免费层终止，216 条文本 500 |
| `OpenaiChat` / `ChatGPT` | 空回复（#3525）、token 失效（#3515） |
| `Qwen` 网页版 | 42 条 500，唯一可用模型 8.4s |
| `Antigravity` / `GeminiCLI` | 社区反馈杀号严重（上午用下午封），不适合长期反代 |
| `AgentTools` | 21s，是 Agent 工具层而不是对话上游 |

---

## 4. 质量：免费模型的天花板在哪

ClawLabs 的每日免费模型评分（0–100，benchmark + Arena 合成）：

| 模型（OpenRouter `:free`） | 分数 | tools | 服务方是否会拿你的 prompt 训练 |
|---|---:|---|---|
| `thinkingmachines/inkling` | 67.6 | ✓ | 会 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 65.8 | ✓ | 会 |
| `thinkingmachines/inkling-small` | 64.8 | ✓ | 会 |
| `nvidia/nemotron-3.5-super-vl` | 60.8 | ✓ | 会 |
| `google/gemma-4-31b-it` | 57.1 | ✓ | 不会（保留 55 天） |
| `google/gemma-4-26b-a4b-it` | 55.0 | ✓ | 不会 |
| `nvidia/nemotron-3-super-120b-a12b` | 45.5 | ✓ | 会 |
| `cohere/north-mini-code` | 23.0 | ✓ | 不会 |

参考系：顶级商业模型约 100 分。也就是说**免费通道最好也只有 6 成水平**，
做 Agent 的规划/多步推理会明显吃力；适合做「工具调用 + 格式化 + 简单问答」这类执行层。

---

## 5. 最终推荐（针对反代 API + Agent）

### 5.1 免 key 组合（零成本）

| 优先级 | 供应商 | 模型 | 理由 | 风险 |
|---:|---|---|---|---|
| 1 | `KiloCode` | `kilo-auto/free` | 0.5–4s、原生 tools、OpenAI 协议 | 200 次/小时/IP；免费池漂移 |
| 2 | `LLM7` | `default` | 1s、匿名、原生 tools | 单模型，能力有限 |
| 3 | `Perplexity` | `auto` / `claude45sonnet` | 质量最高 | 429、无原生 tools、逆向 |
| 4 | `Cloudflare` | `glm-5.2` | 极稳 | 12–40s、需浏览器，仅兜底 |

### 5.2 加一个免费 key（推荐长期方案）

| 优先级 | 供应商 | 模型 | 理由 |
|---:|---|---|---|
| 1 | `GeminiPro` | `gemini-2.5-flash` | 社区公认最稳，原生 tools，质量/速度均衡 |
| 2 | `Groq` | `openai/gpt-oss-120b` | 延迟最低，1,000 RPD |
| 3 | `KiloCode` | `kilo-auto/free` | 不用 key 的备胎 |
| 4 | `LLM7` | `default` | 最后兜底 |

### 5.3 `config.yaml`（放到 `~/.g4f/cookies/config.yaml`）

```yaml
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
      - provider: "Cloudflare"
        model: "glm-5.2"        # 最后兜底，慢但活

  - name: "agent-quality"
    providers:
      - provider: "GeminiPro"
        model: "gemini-2.5-flash"
      - provider: "Groq"
        model: "openai/gpt-oss-120b"
      - provider: "KiloCode"
        model: "kilo-auto/free"

  - name: "agent-fast"
    providers:
      - provider: "Groq"
        model: "openai/gpt-oss-120b"
      - provider: "KiloCode"
        model: "kilo-auto/free"
      - provider: "LLM7"
        model: "default"
```

启动时排除已知坏通道：

```dotenv
G4F_API_KEY=<随机长串>
G4F_IGNORED_PROVIDERS=Puter,Airforce,Pollinations,Qwen,OpenaiChat,AgentTools
G4F_TIMEOUT=120
G4F_STREAM_TIMEOUT=120
```

---

## 6. Agent 专用注意事项

1. **版本必须 ≥ 8.8.0**。当前代码里 `ToolCallModel` 会补 `index`、把 `arguments` 强制序列化成 JSON 字符串，
   这正是 2026-03（g4f.dev #70）和 2026-09（#3527）把 opencode 打崩的原因。老版本会继续踩。
2. **优先原生 tools**。`KiloCode`、`LLM7`、`GeminiPro`、`Groq`、`Nvidia`、`OpenRouterFree`、`HuggingFace`、`You` 都声明了 `supports_native_tools`；
   `Perplexity`、`Cloudflare`、`Qwen` 走模拟，请求数翻倍、更容易超时。
3. **流式反代要关缓冲**（Nginx `proxy_buffering off`），否则 Agent 会一口气等到最后。
4. **别用默认 `auto` 路由**。`g4f/models.py` 的默认顺序仍以 `CopilotApp/Ollama/DeepInfra/OperaAria/GLM/Pollinations/Qwen…` 开头，
   与本次实测的可用性完全相反；用 `config.yaml` 覆盖。
5. **每日复测**，把 `scripts/bench_providers.py --all-public --quick` 挂 cron，免费池一周能变两次。

---

## 7. 成本/合规提醒

- 免费推理的代价通常是**你的 prompt 会被用于训练**（上表 `是否会训练`）；涉及客户数据时不要走免费层。
- `NVIDIA NIM` 条款是 evaluation-only，`Cohere` 免费 key 禁止个人用途，`Gemini` 免费层在 EEA/UK/CH 有额外限制。
- `Antigravity`/`GeminiCLI` 这类 OAuth 通道存在封号风险，不适合拿主账号长期反代。
- 对外提供服务时务必设置 `G4F_API_KEY`，否则等于开放一个无鉴权的公网代理。

---

## 8. 复现方式

```bash
# 1) 本地实测（你自己的出口 IP，比 GitHub runner 更真实）
python scripts/bench_providers.py --providers KiloCode,LLM7,Perplexity,Cloudflare --details

# 2) 压测已部署的反代
python scripts/bench_providers.py --base-url http://127.0.0.1:8080/v1 \
  --api-key "$G4F_API_KEY" --models agent-primary,agent-quality

# 3) 每天拉社区实测结果做交叉验证
curl -s https://raw.githubusercontent.com/Free-AI-Things/g4f-working/main/working/working_results.txt \
  | cut -d'|' -f1 | sort | uniq -c | sort -rn
```
