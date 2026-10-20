# Windows 11 一键运行方案

目标：**双击一个图标**，就得到一个带密钥的本地 OpenAI 兼容反代，给 dsh / Cursor / Cherry Studio 用。
不需要装 Python，不需要开命令行，不需要记参数。

---

## 一、先给结论

| 方案 | 产物 | 用户侧需要什么 | 首次启动 | 体积 | 可离线 | 评价 |
|---|---|---|---|---|---|---|
| **A. 免构建启动器** | `G4F-Proxy.cmd` | 双击 + 联网（首次） | 1–3 min 装依赖 | < 1 KB | 之后可 | 最省事，随时跟随仓库更新 |
| **B. PyInstaller 单文件** | `g4f-proxy.exe` | 双击 | 4–8 s | 见下方实测 | ✅ 完全离线 | **推荐主方案**，真·单个程序 |
| **C. 便携目录** | `g4f-proxy-portable.zip` | 解压后双击 | 1–2 s | 同 B，解压后约 200 MB | ✅ | B 的稳健版，启动快，杀软误报少 |
| D. Nuitka / MSVC | `g4f-proxy.exe` | 双击 | 1–3 s | 类似 | ✅ | 需要 VS Build Tools，编译 20+ 分钟，收益不大 |
| E. Docker Desktop | 镜像 | 装 Docker + WSL2 | — | GB 级 | ✅ | 不符合"一键"，不推荐 |

**已实测：** 方案 B/C 已在 **GitHub Actions 的 windows-latest** 上真实构建通过（下文的 CI 工作流），
产物上传为 artifact `g4f-proxy-windows-x64`，**130.0 MB**（单文件 exe + 便携包，压缩后合计）。
构建日志中的 `Report sizes` 步骤会打印两个文件各自的大小。CI 里的两步冒烟测试全部通过：
`--print --json` 拿到 base_url/api_key，以及真实启动服务后 `GET /v1/models` 返回 200。

同一份 spec 和启动逻辑在 Linux 上也验证过（PyInstaller 不能跨平台交叉编译，exe 只能在 Windows 上产出，
所以 Windows 侧走 CI 或你本机的一行命令）。

---

## 二、方案 A：双击即用（零构建）

仓库里已经放好：

```
packaging\win\G4F-Proxy.cmd
```

1. 把仓库下载/克隆到本机（任意目录）。
2. 双击 `packaging\win\G4F-Proxy.cmd`。
3. 第一次运行：如果没装 [uv](https://docs.astral.sh/uv/)，脚本会**静默装到用户目录**（不需要管理员），
   然后自动建虚拟环境、装依赖（1–2 分钟），再启动服务。
4. 窗口里会打印：

```
 base URL  : http://127.0.0.1:8080/v1
 api key   : g4f_xxxxxxxx…
```

之后每次双击约 2 秒启动（依赖已缓存）。

带参数也可以直接双击不了，就在终端里：

```bat
packaging\win\G4F-Proxy.cmd --dsh --set-default
packaging\win\G4F-Proxy.cmd --port 9000
packaging\win\G4F-Proxy.cmd --host 0.0.0.0      :: 局域网/手机访问，会弹防火墙授权
```

> 默认只监听 `127.0.0.1`（Windows 上是有意的）：不弹防火墙、不暴露到局域网。
> 需要别的设备连，显式加 `--host 0.0.0.0`。

---

## 三、方案 B：构建真正的单文件 exe

### 3.1 前置

- Windows 10/11 x64
- Python 3.10+（推荐 3.12；[python.org](https://www.python.org/downloads/) 安装时勾选 *Add python.exe to PATH*）
- 磁盘留 1 GB 给构建缓存

### 3.2 一条命令

```powershell
powershell -ExecutionPolicy Bypass -File packaging\win\build-exe.ps1
```

脚本会：

1. 建 `.build-venv`（不污染全局 Python）
2. 按 `packaging/win/requirements-win.txt` 装依赖 + PyInstaller
3. 生成 `dist\g4f-proxy.exe`（单文件）
4. 生成 `dist\g4f-proxy-portable.zip`（文件夹版，启动更快）
5. **自动冒烟测试**：先跑 `--print --json` 校验密钥，再真的启动服务并请求 `GET /v1/models` 断言 200
6. 打印体积

常用变体：

```powershell
# 只要单文件，跳过文件夹版
... -OneFileOnly

# 顺便在桌面放一个快捷方式
... -CreateShortcut

# 跳过冒烟测试（不建议）
... -SkipTest
```

### 3.3 产物

```
dist\g4f-proxy.exe              ← 拷给别人就能用
dist\g4f-proxy-portable.zip     ← 解压双层，启动快、误报少
```

`g4f-proxy.exe` 双击 → 打印 key（**已自动复制到剪贴板**）→ 服务起在 `http://127.0.0.1:8080/v1`。

接 DeepSeek Harness：

```powershell
.\dist\g4f-proxy.exe --dsh --set-default
# 另开窗口
$env:G4F_API_KEY = Get-Content .g4f-api-key
npx @deepseek-ai/dsh web
```

### 3.4 它到底"简化"了什么

| 项 | 仓库全量 | 打包产物 |
|---|---|---|
| 入口 | api / gui / client / mcp / tray / locals | 只有 `g4f-api` |
| Python 模块 | 全部 | 234 个（`g4f/**`，去掉 markitdown 集成） |
| 依赖 | `requirements.txt` 23 个 + 各种 extra | 同 23 个，**不含** wasmtime / markitdown / pystray / cairosvg / gpt4all / torch |
| 图形界面 / 托盘 / 本地模型 | 有 | **没有**（`--no-gui`） |
| 启动方式 | `python -m g4f ...` | 双击 |
| 密钥 | 自己设 | 自动生成、复用、复制到剪贴板 |

打包用的是 `packaging/win/g4f-proxy.spec`，其中：

- **不 import g4f** 来决定要收哪些模块，而是直接遍历源码树（234 个），
  所以**离线也能构建**，也不会被某个需要联网的 provider 卡住构建；
- `curl_cffi` / `primp` / `cryptography` / `lxml` 等带二进制的包用 `collect_all` 收全；
- uvicorn 的 loop/protocol/lifespan 是运行时字符串导入，单独列进 hiddenimports；
- `g4f/providers.json`、`providers.html`、`AliyunCaptcha.js.txt`、`pow_solver.wasm` 作为 data 打进去。

构建前可以先自检（不需要 PyInstaller，秒级）：

```powershell
python packaging\win\validate_spec.py
# g4f modules to freeze : 234
# third-party packages  : 14
# data files            : 5
# OK - spec inputs are complete
```

---

## 四、方案 C：不装 Python，云端出 exe

仓库里带了 `.github/workflows/build-windows.yml`：

1. 把仓库 push 到你自己的 GitHub。
2. **Actions → build-windows-exe → Run workflow**。
3. 约 3–5 分钟（实测 3 分 09 秒），在 Artifacts 里下载 `g4f-proxy-windows-x64`
   （含 `g4f-proxy.exe` 和 `g4f-proxy-portable.zip`）。
4. 打 tag（`v1.0.0`）也会自动触发。

CI 里跑的和本机完全一样的两项冒烟测试（`--print --json` + 真实请求 `/v1/models`），
任一步失败都不会产出 artifacts。

> 注意：fork 仓库默认可能需要你在 **Settings → Actions → General** 里允许工作流。

---

### 4.1 已经跑通的这次构建

| | |
|---|---|
| 仓库 | `yzj7777/gpt4free`（分支 `arena/de64e7c6-gpt4free`） |
| 运行 | `build-windows-exe` #39406396640 ✅，耗时 **3 分 32 秒**（同一提交上完整通过） |
| 产物 | `g4f-proxy-windows-x64`，**130.0 MB**（exe + 便携包，压缩后） |
| 验证 | `--print --json` ✅ / 启动服务 + `GET /v1/models` 200 ✅ |

页面路径：`Actions → build-windows-exe → 最近一次运行 → Artifacts`。

## 五、用起来之后

### 5.1 拿到 key 和 url

- 窗口直接打印；
- 程序自动写 `.g4f-api-key`（exe 所在目录，600/隐藏）；
- 想重新生成：`g4f-proxy.exe --rotate-key`；
- 只想看不启动：`g4f-proxy.exe --print`（或 `--print --json` 给脚本用）。

### 5.2 接到客户端

| 客户端 | 填什么 |
|---|---|
| OpenAI SDK / Cherry Studio / ChatBox | Base URL `http://127.0.0.1:8080/v1`，API Key 用上面的 key |
| DeepSeek Harness | `g4f-proxy.exe --dsh --set-default`，然后 `$env:G4F_API_KEY="..."` 再 `npx @deepseek-ai/dsh web` |
| Cursor / Continue | 同上，模型名填 `agent-primary` 或 `agent-fast` |

可用模型名（route，带多供应商回退）：

```
agent-primary    KiloCode → LLM7 → Perplexity → OpenRouterFree → Nvidia
agent-fast      Groq → KiloCode → LLM7
agent-quality   GeminiPro → Groq → KiloCode
```

`GET /v1/models` 会把这三个名字一起列出来（`owned_by: route`）。

### 5.3 开机自启（可选）

1. `Win + R` → `shell:startup`
2. 把 `g4f-proxy.exe` 的快捷方式丢进去
3. 右键快捷方式 → 属性 → 目标 后面加 ` --port 8080`

想静默启动，把快捷方式属性里的"运行方式"设为"最小化"。

### 5.4 端口被占用

不带 `--port` 时，程序发现默认端口被占会自动往后找（8081…8090）并在窗口里提示。
显式指定了 `--port` 则不做这件事，直接报错，避免你以为在 8080 其实不是。

---

## 六、排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 双击后窗口闪一下就没了 | 启动报错 | 用 PowerShell 运行 `.\g4f-proxy.exe` 看完整堆栈；或看窗口里的 `[!] g4f-api exited with code N` |
| SmartScreen "Windows 已保护你的电脑" | 未签名的自编译 exe | 更多信息 → 仍要运行；或用方案 C 的便携版 |
| 杀软报毒 | PyInstaller 单文件的通病 | 用 `g4f-proxy-portable.zip`（文件夹版），误报明显更少 |
| 首次启动要 5–8 秒 | 单文件每次解压到临时目录 | 正常；要快就用便携版 |
| 弹防火墙 | 用了 `--host 0.0.0.0` | 允许专用网络即可；只本机用就别加这个参数 |
| 客户端 401 | 没带 key | `Authorization: Bearer <key>` 或请求头 `g4f-api-key: <key>` |
| dsh 里 401 | 启动 dsh 的窗口没设环境变量 | `$env:G4F_API_KEY = Get-Content .g4f-api-key`（`apiKeyEnv` 是每次请求解析的） |
| dsh 里 Fetch models 拿不到 | 服务没起 / 端口不对 | 浏览器打开 `http://127.0.0.1:8080/v1/models` 看是否有 `agent-*` |
| 起来但全部 500 / `Request execution failed` | 上游供应商当天不可用 | 换模型试 `agent-fast`；或 `--reset-routes` 重写回退链 |
| 构建报 `libpython3.11.so not found` | 在 Linux/WSL 里跑了 spec | exe 只能在 Windows 上构建，用方案 A 或 C |
| 构建报缺包 | requirements 没装全 | 直接重跑 `build-exe.ps1`，它用的是隔离的 `.build-venv` |

---

## 七、文件清单

```
G4F-Proxy.cmd                     方案 A：双击启动（位于 packaging\win\）
```

```
packaging/win/
├── entry.py                      PyInstaller 入口
├── g4f-proxy.spec                打包清单（模块/数据/排除项）
├── build-exe.ps1                 方案 B：一条命令出 exe + 便携包 + 冒烟测试
├── requirements-win.txt          构建依赖（复用根目录 requirements.txt）
├── validate_spec.py              构建前静态自检
└── G4F-Proxy.cmd                 方案 A：零构建启动器
.github/workflows/build-windows.yml   方案 C：云端构建
```
