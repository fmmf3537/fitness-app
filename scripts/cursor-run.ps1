# cursor-run.ps1 - background Cursor Agent CLI (--print headless) slice runner
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cursor-run.ps1 -SliceId <ID> -PromptFile docs/cursor-prompts/<ID>.md
# Outputs: logs/cursor/<ID>.log + <ID>.exitcode + <ID>.pid + <ID>-run.cmd (fallback for user local run)
#
# 2026-09-10 升级（E2E-P0 排障实测）：
#   1. probe 改用 Node（curl 在部分沙箱/Windows 返回 000 误报；Node https 实测 200 OK）
#   2. root 向上推导：脚本可从项目 scripts/ 或 .dsh/skills/.../scripts/ 任意位置运行
#   3. CURSOR_CONFIG_DIR / CURSOR_DATA_DIR 重定向到工作区 .dsh\cursor\，
#      绕过沙箱对 ~/.cursor 的写入限制（EPERM mkdir ~/.cursor/chats 是 agent 崩溃真因）
param(
    [Parameter(Mandatory = $true)][string]$SliceId,
    [Parameter(Mandatory = $true)][string]$PromptFile
)

$ErrorActionPreference = 'Stop'

# Repair PATH for sandbox-launched processes (harness PATH may lack node/System32/git)
$env:PATH = 'C:\Program Files\nodejs;C:\Program Files\Git\cmd;C:\Windows\System32;C:\Windows\System32\WindowsPowerShell\v1.0;' + $env:PATH
# Repair PATHEXT (harness may break it, e.g. ".CPL" only, so node.exe/git.exe never resolve)
$env:PATHEXT = '.COM;.EXE;.BAT;.CMD;.VBS;.JS;.WS;.MSC;.CPL'

# ===== root 推导：向上找含 pnpm-workspace.yaml 或 docs\cursor-prompts 的目录 =====
$candidate = Split-Path -Parent $PSScriptRoot
$root = $null
for ($i = 0; $i -lt 6; $i++) {
    if ((Test-Path (Join-Path $candidate 'pnpm-workspace.yaml')) -or (Test-Path (Join-Path $candidate 'docs\cursor-prompts'))) {
        $root = $candidate
        break
    }
    $parent = Split-Path -Parent $candidate
    if ($parent -eq $candidate) { break }
    $candidate = $parent
}
if (-not $root) { $root = Split-Path -Parent $PSScriptRoot }

$logDir = Join-Path $root 'logs\cursor'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir "$SliceId.log"
$exitFile = Join-Path $logDir "$SliceId.exitcode"
$taskFile = Join-Path $logDir "$SliceId.task.txt"
$runCmd = Join-Path $logDir "$SliceId-run.cmd"

$promptPath = Join-Path $root ($PromptFile -replace '/', '\')
if (-not (Test-Path $promptPath)) { throw "prompt file missing: $promptPath" }

$task = "You are a senior full-stack engineer in this repo. First read the file $promptPath (a detailed dev task prompt). Then strictly follow it to complete the development. Obey all red lines and forbidden-file rules. Finally output the complete delivery report as your final reply. Output your plan first, then act directly, do not wait for confirmation."
[System.IO.File]::WriteAllText($taskFile, $task + "`r`n")

Remove-Item $log, $exitFile -ErrorAction SilentlyContinue

# ===== Step 1: network probe（Node，不用 curl —— curl 在部分沙箱 000 误报）=====
Write-Host "[probe] Testing Cursor API connectivity..."
$probe = & node -e "const https=require('https');const r=https.get('https://api2.cursor.sh/',{timeout:6000},res=>{console.log(res.statusCode);process.exit(0)});r.on('error',e=>{console.log('FAIL: '+e.code);process.exit(1)});r.on('timeout',()=>{console.log('TIMEOUT');process.exit(2)});" 2>&1
$probe = ($probe | Out-String).Trim()
Write-Host "[probe] api2.cursor.sh = $probe"
$netOk = ($probe -eq '200')

if (-not $netOk) {
    # 生成降级 run.cmd（本机非沙箱 shell 双击）
    $nl = [Environment]::NewLine
    $cmdBody = '@echo off' + $nl
    $cmdBody += 'chcp 65001 >nul' + $nl
    $cmdBody += 'set "CURSOR_CONFIG_DIR=' + (Join-Path $root '.dsh\cursor\config') + '"' + $nl
    $cmdBody += 'set "CURSOR_DATA_DIR=' + (Join-Path $root '.dsh\cursor\data') + '"' + $nl
    $cmdBody += '"%LOCALAPPDATA%\cursor-agent\agent.cmd" --print --trust -e https://api2.cursor.sh --workspace "' + $root + '" < "' + $taskFile + '" > "' + $log + '" 2>&1' + $nl
    $cmdBody += 'echo %ERRORLEVEL% > "' + $exitFile + '"' + $nl
    [System.IO.File]::WriteAllText($runCmd, $cmdBody, [System.Text.UTF8Encoding]::new($false))
    Write-Warning "NETWORK BLOCKED: api2=$probe. Cursor agent cannot start in this sandbox."
    Write-Warning "Fallback run.cmd created: $runCmd"
    Write-Warning "Ask user to double-click $runCmd on local (non-sandbox) shell, then paste $log back for review."
    exit 2
}

# ===== Step 2: start agent（exec.cmd 与 run.ps1 同目录，或项目 scripts\ 下）=====
$execCandidates = @(
    (Join-Path $PSScriptRoot 'cursor-exec.cmd'),
    (Join-Path $root 'scripts\cursor-exec.cmd')
)
$execScript = $execCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $execScript) { throw "cursor-exec.cmd not found" }

$proc = Start-Process -FilePath $execScript -ArgumentList $SliceId -WindowStyle Hidden -PassThru
[System.IO.File]::WriteAllText((Join-Path $logDir "$SliceId.pid"), [string]$proc.Id)
Write-Output "STARTED slice=$SliceId pid=$($proc.Id) log=$log (network probe passed)"

# ===== Step 3: 5s health check =====
Start-Sleep -Seconds 5
$alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
$logSize = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
if (-not $alive -and $logSize -eq 0) {
    Write-Warning "DEAD after 5s (pid gone, log empty). Likely sandbox/network blocked."
    Write-Warning "Ask user to run $runCmd locally, paste $log back."
    exit 3
}
Write-Output "Health OK: pid=$($proc.Id) alive, log start=$logSize bytes"

# 提示等待（不阻塞）：用 wait-slice.ps1 后台盯 exitcode
Write-Output "Next: powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\wait-slice.ps1 -Root $root -Id $SliceId -TimeoutMin 45"