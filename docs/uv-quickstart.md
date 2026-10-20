# 用 uv 一键跑 g4f 反代 API

面向「本机起一个 OpenAI 兼容接口，给 dsh / Cursor / Cherry Studio 用」的场景。
uv 负责环境，一条命令负责密钥、路由、启动。

---

## 0. 前置条件

```bash
# 安装 uv（三选一）
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
brew install uv                                    # macOS
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

- Python：`uv` 会自动找 3.10+，找不到就 `uv python install 3.12`
- Node `^22.19` 或 `>=24`：**只有**接 DeepSeek Harness 时才需要
- 浏览器：**可选**。装了 Chrome/Chromium 会自动启用 Cloudflare 兜底；没装则走纯 HTTP 供应商

---

## 1. 一条命令

```bash
cd gpt4free
uv run g4f-api --dsh --set-default
```

第一次运行会依次完成：

| 步骤 | 说明 | 产物 |
|---|---|---|
| `uv sync` | 建 `.venv`、装 `requirements.txt` 同款依赖、把仓库以可编辑方式装进去 | `.venv/`、`uv.lock` |
| provider 目录 | 拉 `g4f.dev` 的目录缓存；拉不到写内置 stub，**离线也能启动** | `~/.g4f/cache/.models/<日期>/providers.json` |
| 密钥 | 复用 `.g4f-api-key`，没有就生成 `g4f_...` | `.g4f-api-key`（600） |
| 路由 | 写 `agent-primary` / `agent-fast` / `agent-quality` 三条多供应商回退链 | `~/.g4f/cookies/config.yaml` |
| dsh | 把 `g4f` provider 合并进 dsh 配置（自动备份、幂等） | `~/.dsh/settings.yaml` |
| 启动 | `python -m g4f --no-gui --bind 0.0.0.0:8080`，轮询端口后打印面板 | — |

启动后终端会直接打印你要的两样东西：

```
▸ proxy is ready → http://127.0.0.1:8080/v1

──────────────────────────────────────────────────────────────
 base URL  : http://127.0.0.1:8080/v1
 api key   : g4f_LKDr…   (/home/you/gpt4free/.g4f-api-key)
 routes    : /home/you/.g4f/cookies/config.yaml
──────────────────────────────────────────────────────────────
```

---

## 2. 只想要 key 和 url（不启动）

```bash
uv run g4f-api --print                 # 人类可读面板
uv run g4f-api --print --json          # 机器可读
uv run g4f-api --print --json --port 9000
```

接到其他工具里：

```bash
# 一次性导进当前 shell（不依赖 jq）
read -r OPENAI_BASE_URL OPENAI_API_KEY <<<"$(uv run g4f-api --print --json \
  | python -c 'import json,sys; d=json.load(sys.stdin); print(d["base_url"], d["api_key"])')"
export OPENAI_BASE_URL OPENAI_API_KEY

# 或者有 jq 的话
export OPENAI_API_KEY=$(uv run g4f-api --print --json | jq -r .api_key)
```

> `--json` 模式下进度信息走 **stderr**，stdout 只有一段 JSON，可以安全管道。

### 重新生成密钥

```bash
uv run g4f-api --rotate-key            # 换新 key 并启动
uv run g4f-api --rotate-key --print    # 只换 key，不启动
```

旧 key 立即失效（服务重启后生效）。密钥来源优先级：

```
G4F_API_KEY 环境变量  >  .g4f-api-key 文件  >  自动生成
```

想强制用某个固定的 key（例如写进 docker-compose）：

```bash
G4F_API_KEY=g4f_my_fixed_key uv run g4f-api
```

---

## 3. 常用组合

```bash
# 换端口 / 只听本机
uv run g4f-api --port 9000
uv run g4f-api --bind 127.0.0.1:9000

# 只要 API，不写 dsh 配置
uv run g4f-api

# 写完配置就退出（CI / 只准备环境）
uv run g4f-api --dsh --print

# 覆盖已有路由（会留 .bak 备份）
uv run g4f-api --reset-routes

# 起服务同时拉起 dsh web
uv run g4f-api --dsh --launch-dsh

# 自定义写进 dsh 的模型名
uv run g4f-api --dsh --models agent-primary,agent-fast
```

### 完全不用 pyproject / console script

如果不想让 uv 管这个仓库（例如只想临时跑一下），也可以：

```bash
uv run --no-project --with-requirements requirements.txt \
  python -m g4f --no-gui --bind 0.0.0.0:8080
```

这种方式不会安装 `g4f-api` 命令，也**不会**帮你生成 key 和路由 —— 适合快速验证。
注意此时服务**没有鉴权**，绑 `0.0.0.0` 等于对局域网完全开放，日常请用 `uv run g4f-api`。

---

## 4. 和 `scripts/run-agent-proxy.sh` 的关系

| | `uv run g4f-api` | `bash scripts/run-agent-proxy.sh` |
|---|---|---|
| 环境 | uv 管（`uv sync`） | 自己建 `venv` + `pip` |
| 密钥 / 路由 / dsh | 同一套逻辑（Python 实现） | 同一套逻辑（Bash 实现） |
| 适用 | 有 uv 的机器，推荐 | 只有 pip、或想用 `--launch-dsh` 的一体化脚本 |

两边产物路径完全一致（`.g4f-api-key`、`~/.g4f/cookies/config.yaml`），可以混用。

---

## 5. 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| `error: No pyproject.toml found` | 不在仓库根目录 | `cd gpt4free` 再执行 |
| `Failed to spawn: g4f-api` | 旧版 `uv run` 没装脚本 | `uv sync --reinstall-package g4f` |
| `ValueError: not enough values to unpack` | 手动用了 `--bind 0.0.0.0` 没带端口 | `--bind 0.0.0.0:8080` |
| 启动卡住 / `SSLError g4f.dev` | 拉不到 provider 目录 | 正常，会用内置 stub 启动；想强制重拉删掉 `~/.g4f/cache/.models/<日期>/` |
| `401 Unauthorized` | 客户端没带 key | `Authorization: Bearer $(cat .g4f-api-key)`，或 `g4f-api-key:` 头 |
| dsh 里模型列表点 "Fetch" 只有几个 | 5 分钟缓存 | 重启服务，或 `curl /v1/models` 确认 `agent-*` 已出现 |
| `RuntimeError: Chrome executable not found` | 兜底链里用了 Cloudflare | 用 `--reset-routes` 重写路由（脚本会按浏览器探测结果改写） |
| `uv.lock` 冲突 | 上游没提交该文件 | 本仓库已 gitignore，可随时删除 |

### 验证服务真的活着

```bash
K=$(cat .g4f-api-key)
curl -s -o /dev/null -w '%{http_code}\n' $([ -n "$K" ] && echo "-H \"Authorization: Bearer $K\"") http://127.0.0.1:8080/v1/models   # 401
curl -s -H "Authorization: Bearer $K" http://127.0.0.1:8080/v1/models | python -m json.tool | head -20   # 200
```

`/v1/models` 里能看到 `agent-primary` / `agent-fast` / `agent-quality` 三个路由名，
说明 `config.yaml` 已生效；dsh 的 "Fetch available models" 也能直接取到它们。

---

## 6. 清理

```bash
rm -rf .venv uv.lock            # uv 环境
rm -f  .g4f-api-key             # 密钥（会让现有客户端 401）
rm -rf ~/.g4f/cookies/config.yaml ~/.g4f/cache   # 路由 + 目录缓存
```
