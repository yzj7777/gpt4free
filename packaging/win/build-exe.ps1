<#
.SYNOPSIS
    Build g4f-proxy.exe (one file) and g4f-proxy-portable.zip (folder build).

.DESCRIPTION
    Run this on Windows 11/10 with Python 3.10+ (3.12 recommended) on PATH.
    Everything happens inside .build-venv, so your global Python is untouched.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\win\build-exe.ps1
    powershell -ExecutionPolicy Bypass -File packaging\win\build-exe.ps1 -OneFileOnly -CreateShortcut
#>
[CmdletBinding()]
param(
    # only build the single-file exe, skip the portable folder build
    [switch]$OneFileOnly,
    # skip the smoke test (not recommended)
    [switch]$SkipTest,
    # put a shortcut to the exe on the Desktop
    [switch]$CreateShortcut,
    # extra args for the smoke test, e.g. -TestArgs '--port','9123'
    [string[]]$TestArgs = @('--port', '8123')
)

$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..\..'))   # repo root
$root = (Get-Location).Path
$dist = Join-Path $root 'dist'
$venv = Join-Path $root '.build-venv'
$py   = Join-Path $venv 'Scripts\python.exe'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

Step "checking Python"
$python = $null
foreach ($cand in @('py -3.12', 'py -3.11', 'py -3.10', 'python')) {
    $parts = $cand.Split(' ')
    $exe = $parts[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $ver = & $exe @($parts[1..($parts.Length-1)]) -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]'3.10') {
            $python = $cand; Write-Host "    $cand -> Python $ver"; break
        }
    }
}
if (-not $python) { Fail "Python 3.10+ not found. Install from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }

Step "creating build venv (.build-venv)"
if (-not (Test-Path $py)) {
    & cmd /c "$python -m venv `"$venv`"" || Fail "venv creation failed"
}
& $py -m pip install --upgrade pip --quiet
& $py -m pip install --quiet -r (Join-Path $root 'packaging\win\requirements-win.txt') || Fail "dependency install failed"

Step "building one-file exe"
$env:G4F_ONEFILE = '1'
& $py -m PyInstaller (Join-Path $root 'packaging\win\g4f-proxy.spec') `
    --noconfirm --clean --distpath $dist --workpath (Join-Path $root 'build\pyinstaller') `
    --log-level WARN
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed (see build\pyinstaller)" }
$onefile = Join-Path $dist 'g4f-proxy.exe'
if (-not (Test-Path $onefile)) { Fail "expected $onefile" }
$size = [math]::Round((Get-Item $onefile).Length / 1MB, 1)
Write-Host "    $onefile  ($size MB)" -ForegroundColor Green

if (-not $OneFileOnly) {
    Step "building portable folder"
    $env:G4F_ONEFILE = '0'
    & $py -m PyInstaller (Join-Path $root 'packaging\win\g4f-proxy.spec') `
        --noconfirm --clean --distpath $dist --workpath (Join-Path $root 'build\pyinstaller') `
        --log-level WARN
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller (onedir) failed" }
    $portable = Join-Path $dist 'g4f-proxy-portable.zip'
    if (Test-Path $portable) { Remove-Item $portable -Force }
    Compress-Archive -Path (Join-Path $dist 'g4f-proxy\*') -DestinationPath $portable -CompressionLevel Optimal
    $zipSize = [math]::Round((Get-Item $portable).Length / 1MB, 1)
    Write-Host "    $portable  ($zipSize MB)" -ForegroundColor Green
}

if (-not $SkipTest) {
    Step "smoke test: --print --json"
    $json = & $onefile --print --json 2>$null | Out-String
    if ($LASTEXITCODE -ne 0) { Fail "exe exited with $LASTEXITCODE" }
    try { $cfg = $json | ConvertFrom-Json } catch { Fail "not JSON:`n$json" }
    if (-not $cfg.base_url) { Fail "no base_url in output" }
    Write-Host "    base_url=$($cfg.base_url)  key=$($cfg.api_key.Substring(0,8))..." -ForegroundColor Green

    Step "smoke test: start, call /v1/models, stop"
    $port = ($cfg.base_url -replace '.*:(\d+)/.*', '$1')
    $proc = Start-Process -FilePath $onefile -ArgumentList @('--no-copy', '-port', $port) -PassThru -WindowStyle Hidden
    try {
        $ok = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/v1/models" -Headers @{ Authorization = "Bearer $($cfg.api_key)" } -TimeoutSec 3 -UseBasicParsing
                if ($r.StatusCode -eq 200) { $ok = $true; break }
            } catch { }
            if ($proc.HasExited) { Fail "exe exited early ($($proc.ExitCode))" }
        }
        if (-not $ok) { Fail "server did not answer on port $port" }
        $count = ($r.Content | ConvertFrom-Json).data.Count
        Write-Host "    GET /v1/models -> 200, $count models" -ForegroundColor Green
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    }
}

if ($CreateShortcut) {
    Step "creating desktop shortcut"
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnk = Join-Path $desktop 'g4f proxy.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $onefile
    $sc.Arguments = ''
    $sc.WorkingDirectory = $dist
    $sc.Description = 'Local OpenAI-compatible g4f proxy'
    $sc.Save()
    Write-Host "    $lnk" -ForegroundColor Green
}

Step "done"
Write-Host @"
Distribute either of:
  $onefile
  $(Join-Path $dist 'g4f-proxy-portable.zip')

Double-click the exe. It prints the API key, copies it to the clipboard and
serves http://127.0.0.1:8080/v1 . For DeepSeek Harness:
  g4f-proxy.exe --dsh --set-default
"@ -ForegroundColor Gray
