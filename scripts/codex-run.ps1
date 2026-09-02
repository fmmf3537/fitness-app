# codex-run.ps1 — 以后台方式运行 codex exec 执行一个开发切片（通用版）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/codex-run.ps1 -SliceId <ID> -PromptFile docs/cursor-prompts/<ID>.md
# 产物: logs/codex/<ID>.log（实时输出）+ <ID>.last.md（最终回复）+ <ID>.exitcode + <ID>.pid
# 约定: 本脚本须位于 <项目根>\scripts\ 下，项目根自动解析为脚本目录的上一级
param(
    [Parameter(Mandatory = $true)][string]$SliceId,
    [Parameter(Mandatory = $true)][string]$PromptFile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs\codex'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir "$SliceId.log"
$lastMsg = Join-Path $logDir "$SliceId.last.md"
$exitFile = Join-Path $logDir "$SliceId.exitcode"
$taskFile = Join-Path $logDir "$SliceId.task.txt"

$promptPath = Join-Path $root ($PromptFile -replace '/', '\')
if (-not (Test-Path $promptPath)) { throw "提示词文件不存在: $promptPath" }
$task = "你是本仓库的资深全栈工程师。请先用文件读取工具完整阅读 $promptPath（那是一份详尽的开发任务提示词），然后严格按提示词要求在本仓库完成开发。提示词中的红线与禁改清单必须无条件遵守。完成后按提示词中的交付报告模板输出完整交付报告作为你的最终回复。开始执行前先输出你的实施计划，然后直接动手，不要等确认。"
[System.IO.File]::WriteAllText($taskFile, $task + "`r`n")

Remove-Item $log, $exitFile, $lastMsg -ErrorAction SilentlyContinue

# 凭据从 Windows 用户级环境变量注入子进程（不落地、不打印）
# 变量名取决于 ~/.codex/config.toml 中 provider 的 env_key，按实际修改
$env:MINIMAX_API_KEY = [Environment]::GetEnvironmentVariable('MINIMAX_API_KEY', 'User')
# node/npm 全局目录若存在则前置到 PATH（按机器实际路径调整候选列表）
foreach ($p in @("$env:APPDATA\npm", 'C:\Program Files\nodejs')) {
    if (Test-Path $p) { $env:PATH = "$p;$env:PATH" }
}

$proc = Start-Process -FilePath (Join-Path $root 'scripts\codex-exec.cmd') -ArgumentList $SliceId -WindowStyle Hidden -PassThru
[System.IO.File]::WriteAllText((Join-Path $logDir "$SliceId.pid"), [string]$proc.Id)
Write-Output "STARTED slice=$SliceId pid=$($proc.Id) log=$log"
