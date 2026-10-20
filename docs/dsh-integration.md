# 一条命令跑起来，并接进 DeepSeek Harness (dsh)

> 用 uv 的话，`uv run g4f-api --dsh --set-default` 一条命令即可完成本文所有步骤，
> 见 [uv-quickstart.md](uv-quickstart.md)。本文是 pip / 手动配置的完整说明。

> 目标：把 clone 下来的仓库变成一个**带鉴权的本地 OpenAI 兼容反代**，再让 DeepSeek Harness 直接把它当成一个模型供应商。
> 相关：[社区供应商评估](community-provider-eval-2026-10.md) · [基准脚本](provider-agent-benchmark.md)

---

## 1. 前置条件

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+（3.11 / 3.12 最稳） | 脚本会自动建 `.venv` 并装依赖 |
| Node.js | `^22.19` 或 `>=24` | 仅 DeepSeek Harness 需要 |
| Chrome / Chromium | 可选 | 只有 `Cloudflare` 这类通道需要；没有也能跑 |

---

## 2. 一条命令

在仓库根目录：

```bash
bash scripts/run-agent-proxy.sh --dsh --set-default
```

它按顺序做这些事（全部幂等，可重复执行）：

1. 建 `.venv`，装 `requirements.txt`（首次约 1–2 分钟，之后有 stamp 会跳过）；
2. 预置 provider 目录缓存：能连 `g4f.dev` 就拉实时目录，连不上就写最小 stub，**保证离线也能启动**；
3. 生成/复用 API key（`./.g4f-api-key`，权限 600）；
4. 写 `~/.g4f/cookies/config.yaml` 三条模型路由：`agent-primary` / `agent-fast` / `agent-quality`；
5. 检测 Chrome / Lightpanda：有就把 `Cloudflare` 放进兜底，没有就改用 HTTP-only 的 `OpenRouterFree` + `Nvidia`；
6. `--dsh`：把 `g4f` provider 合并进 `~/.dsh/settings.yaml`（自动备份，不覆盖你已有的 provider）；
7. 启动 `python -m g4f --no-gui --bind 0.0.0.0:8080`，等端口就绪后打印用法。

输出大致是：

```
▸ creating venv at /path/gpt4free/.venv
▸ installing requirements (first run takes ~1-2 min)
▸ preparing provider catalog cache
    fetched live catalog from g4f.dev
▸ generated a new API key at /path/gpt4free/.g4f-api-key
▸ route tail: no Chrome/Lightpanda, using HTTP-only fallbacks
▸ wrote routes to /home/you/.g4f/cookies/config.yaml
▸ registering provider in /home/you/.dsh/settings.yaml

──────────────────────────────────────────────────────────────
 API base URL : http://127.0.0.1:8080/v1
 API key      : g4f_ab12cd…
 Routes       : /home/you/.g4f/cookies/config.yaml
 Key file     : /path/gpt4free/.g4f-api-key
...
▸ proxy is ready → http://127.0.0.1:8080/v1
```

此时服务在前台运行，`Ctrl+C` 退出。

### 常用变体

```bash
# 只写配置、不启动（先看生成的文件）
bash scripts/run-agent-proxy.sh --dsh --no-start

# 后台常驻
nohup bash scripts/run-agent-proxy.sh --dsh > g4f-proxy.log 2>&1 &

# 换端口 / 只监听本机
bash scripts/run-agent-proxy.sh --port 9000 --bind 127.0.0.1

# 重建路由文件（会先备份）
bash scripts/run-agent-proxy.sh --reset-routes

# 连 DeepSeek Harness 一起拉起来（真·一条命令）
bash scripts/run-agent-proxy.sh --dsh --set-default --launch-dsh
```

---

## 3. 让 dsh 用上这个代理

### 3.1 已自动写入的配置

`--dsh` 会在 `~/.dsh/settings.yaml`（`DSH_HOME` 可改）里合并出：

```yaml
llm-pi-ai:
  providers:
    g4f:
      displayName: g4f local proxy
      apiKeyEnv: G4F_API_KEY        # 每次请求时从环境变量读取
      api: openai-completions
      baseURL: http://127.0.0.1:8080/v1
      compat:
        supportsDeveloperRole: false   # g4f 只认标准 OpenAI 的 user/assistant 角色
        maxTokensField: max_tokens     # 不发送 max_completion_tokens
      defaultContextWindow: 262144
      defaultMaxTokens: 8192
      models:
        - id: agent-primary
          name: g4f Agent Primary
        - id: agent-fast
          name: g4f Agent Fast
        - id: agent-quality
          name: g4f Agent Quality
agent-default-model:            # 仅 --set-default 时写入
  provider: g4f
  model: agent-primary
```

> `provider` 的 id（这里是 `g4f`）**创建后不可改名**，会话记录、默认值、凭据都绑在它上面；要换只能新建再删旧的。

**关键一步：密钥必须导出在启动 dsh 的那个 shell 里**（`apiKeyEnv` 是每次请求解析的）：

```bash
export G4F_API_KEY=$(cat .g4f-api-key)
npx @deepseek-ai/dsh web
```

然后 `Settings → Models` 里选 `g4f` + `agent-primary`，或直接用（如果用了 `--set-default`）：

```bash
npx @deepseek-ai/dsh
```

### 3.2 手动配置（不想跑脚本时）

Web UI：`Settings → Models → Add a custom provider`

| 字段 | 值 |
|---|---|
| Provider ID | `g4f` |
| Display name | g4f local proxy |
| Base URL | `http://127.0.0.1:8080/v1` |
| API protocol | `openai-completions` |
| API key | `cat .g4f-api-key` 的内容 |

模型列表点 “Fetch available models” **不会**看到 `agent-primary` —— g4f 的 `/v1/models` 只列内置模型和供应商名。请手动添加 `agent-primary`。

或者直接调脚本：

```bash
python scripts/setup-dsh.py --base-url http://127.0.0.1:8080/v1 --set-default
```

### 3.3 最短路径（复用 dsh 的 DeepSeek 通道）

dsh 允许用两个环境变量把「DeepSeek 提供商」整体指向任意 OpenAI 兼容端点：

```bash
export DEEPSEEK_BASE_URL=http://127.0.0.1:8080/v1
export DEEPSEEK_API_KEY=$(cat .g4f-api-key)
export DSH_MODEL=agent-primary
npx @deepseek-ai/dsh web
```

优点是不用改配置文件；缺点是这条通道会按 DeepSeek 方言发送 `thinking` / `reasoningEffort` 等字段，g4f 只是转给上游，兼容性不如 3.1 的自定义 provider。**长期用建议走 3.1。**

> 注意：`DEEPSEEK_BASE_URL` **不能写进仓库根目录的 `.env`**。dsh 会直接报错退出：
> `dsh: .env sets "DEEPSEEK_BASE_URL", which only the launching environment may set`。
> 用 `export` 放在 shell 里。

---

## 4. 验证

```bash
# 1) 反代本身
KEY=$(cat .g4f-api-key)
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8080/v1/models | head -c 200
# 未授权应为 401
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/v1/models

# 2) 真正跑一次对话（走 agent-primary 的 fallback 链）
curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"agent-primary","messages":[{"role":"user","content":"say ok"}]}' \
  http://127.0.0.1:8080/v1/chat/completions

# 3) 工具调用（agent 的关键能力）
curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"agent-primary","stream":false,
       "messages":[{"role":"user","content":"What is the weather in Tokyo? Use the tool."}],
       "tools":[{"type":"function","function":{"name":"get_weather",
         "parameters":{"type":"object","properties":{"city":{"type":"string"}}}}}]}' \
  http://127.0.0.1:8080/v1/chat/completions
```

dsh 侧：

```bash
npx @deepseek-ai/dsh provider validate g4f    # 部分版本提供该命令
npx @deepseek-ai/dsh web                      # 在 UI 里切到 g4f/agent-primary
```

---

## 5. 三条路由分别是什么

脚本写入的 `~/.g4f/cookies/config.yaml`（按 2026-10 的社区实测排序）：

| 路由 | 链 | 适用 |
|---|---|---|
| `agent-primary` | `KiloCode` → `LLM7` → `Perplexity` →（`Cloudflare` 或 `OpenRouterFree`+`Nvidia`） | 日常 agent 默认 |
| `agent-fast` | `Groq` → `KiloCode` → `LLM7` | 多步工具链、低延迟 |
| `agent-quality` | `GeminiPro` → `Groq` → `KiloCode` | 需要更好推理时 |

带 key 的通道（`Groq`、`GeminiPro`）没配 key 时会走 `g4f.space` 公共网关，能不能用取决于公共服务当时的状态。

改路由：直接编辑这个 YAML，或 `--reset-routes` 重新生成，然后**重启服务**（路由在启动时加载）。

---

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| dsh 报 401 | 启动 dsh 的 shell 没有 `G4F_API_KEY`；`export` 后再启动 |
| 请求打到 `/v1/v1/...` 404 | `baseURL` 已含 `/v1`，别再让客户端拼一层；dsh 里填 `http://127.0.0.1:8080/v1` |
| 工具调用 400 / 参数不是 JSON | 老版本 g4f 的 `tool_calls` 缺 `index`、`arguments` 是对象；升级到 **≥ 8.8.0** |
| 返回 `Google Chrome / Chromium not found` | 兜底里含浏览器类供应商；脚本已按检测自动改写，或删掉 `Cloudflare` 条目 / `g4f-go browser install` |
| 首字节很慢 | `agent-primary` 前两级被限流，请求落到 `Cloudflare`（12–40s）；把 `Cloudflare` 移出链或换 `agent-fast` |
| `429` | 免费池限流：Kilo 约 200 次/小时/IP，OpenRouter `:free` 20 RPM / 50 RPD |
| 想换端口 | `--port 9000`，同时 dsh 的 `baseURL` 要跟着改（重跑 `--dsh`） |
| 服务起不来、日志里有 SSL 错误 | 预置目录缓存已兜底；若仍失败，检查是否能访问 `g4f.dev`，或手动指定 `G4F_CACHE_DIR` |

---

## 7. 后台常驻（systemd）

```ini
# /etc/systemd/system/g4f-proxy.service
[Unit]
Description=g4f agent reverse proxy
After=network-online.target

[Service]
Type=simple
User=you
WorkingDirectory=/opt/gpt4free
Environment=G4F_API_KEY=replace-me
ExecStart=/opt/gpt4free/.venv/bin/python -m g4f --no-gui --bind 0.0.0.0:8080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now g4f-proxy
journalctl -u g4f-proxy -f
```

Docker 方式（注意把 `~/.g4f` 挂进去，否则容器里读不到 `config.yaml` 和 `.env`）：

```yaml
services:
  gpt4free:
    image: hlohaus789/g4f:latest
    ports: ["8080:8080"]
    volumes:
      - ~/.g4f:/root/.g4f
    environment:
      - G4F_API_KEY=${G4F_API_KEY}
```

---

## 8. 安全

- `G4F_API_KEY` 一旦设置，所有路由（包括 `/v1`、`/v1/models`）都要鉴权；不设置就是完全公开。
- 不要把 `8080` 直接暴露到公网；必须暴露时套 Nginx，并 `proxy_buffering off;`，否则 SSE 会被整段缓存。
- 密钥文件 `./.g4f-api-key` 已加入 `.gitignore`，不要手动提交或贴到 issue 里。
- 免费通道通常会用你的 prompt 训练，别传客户数据。
