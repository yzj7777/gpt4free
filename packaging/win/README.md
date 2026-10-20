# Windows one-click build

## Just want the exe?

Download it (no GitHub login needed):

- **`g4f-proxy.exe`** (64.6 MB, single file) —
  <https://github.com/yzj7777/gpt4free/releases/download/v0.0.0-win.1/g4f-proxy.exe>
- **`g4f-proxy-portable.zip`** (66.1 MB, faster start) —
  <https://github.com/yzj7777/gpt4free/releases/download/v0.0.0-win.1/g4f-proxy-portable.zip>
- checksums —
  <https://github.com/yzj7777/gpt4free/releases/download/v0.0.0-win.1/SHA256SUMS.txt>

Double-click it. The window shows the API key (also copied to the clipboard) and
serves `http://127.0.0.1:8080/v1`.

## Build it yourself

Two ways to get a double-clickable proxy. Full guide (Chinese): [docs/windows-oneclick.md](../../docs/windows-oneclick.md)

## No build — run from the checkout

Double-click **`G4F-Proxy.cmd`**. On first run it installs `uv` into your user
profile (no admin), creates the venv, then serves `http://127.0.0.1:8080/v1` and
prints the API key.

```bat
G4F-Proxy.cmd --dsh --set-default      :: also register in DeepSeek Harness
G4F-Proxy.cmd --port 9000
G4F-Proxy.cmd --host 0.0.0.0           :: LAN access (opens the firewall prompt)
```

## Build — single exe

Requires Python 3.10+ on PATH.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\win\build-exe.ps1
```

Output:

```
dist\g4f-proxy.exe             single file, double-click
dist\g4f-proxy-portable.zip    folder build, faster start, fewer AV false positives
```

The script ends with a smoke test: it runs `--print --json`, starts the server and
asserts `GET /v1/models` returns 200.

Options: `-OneFileOnly`, `-SkipTest`, `-CreateShortcut`.

## Pre-flight

```powershell
python packaging\win\validate_spec.py
```

Checks that every module the spec freezes is importable by name, that the optional
binary packages exist, and that the runtime data files are present.
