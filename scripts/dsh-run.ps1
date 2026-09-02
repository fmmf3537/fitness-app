# dsh-run.ps1 — 以后台方式运行 dsh headless 执行一个开发切片（通用版）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dsh-run.ps1 -SliceId <ID> -PromptFile docs/cursor-prompts/<ID>.md
# 产物: logs/dsh/<ID>.log（实时输出）+ <ID>.exitcode + <ID>.pid
# 约定: 本脚本须位于 <项目根>\scripts\ 下，项目根自动解析为脚本目录的上一级
param(
    [Parameter(Mandatory = $true)][string]$SliceId,
    [Parameter(Mandatory = $true)][string]$PromptFile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs\dsh'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir "$SliceId.log"
$exitFile = Join-Path $logDir "$SliceId.exitcode"
$taskFile = Join-Path $logDir "$SliceId.task.txt"

# 任务文本保持短（提示词正文由 agent 自己读文件），避开命令行长度上限
$promptPath = Join-Path $root ($PromptFile -replace '/', '\')
if (-not (Test-Path $promptPath)) { throw "提示词文件不存在: $promptPath" }
$task = "你是本仓库的资深全栈工程师。请先用文件读取工具完整阅读 $promptPath（那是一份详尽的开发任务提示词），然后严格按提示词要求在本仓库完成开发。提示词中的红线与禁改清单必须无条件遵守。完成后按提示词中的交付报告模板输出完整交付报告作为你的最终回复。开始执行前先输出你的实施计划，然后直接动手，不要等确认。"
[System.IO.File]::WriteAllText($taskFile, $task + "`r`n")

Remove-Item $log, $exitFile -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath (Join-Path $root 'scripts\dsh-exec.cmd') -ArgumentList $SliceId -WindowStyle Hidden -PassThru
[System.IO.File]::WriteAllText((Join-Path $logDir "$SliceId.pid"), [string]$proc.Id)
Write-Output "STARTED slice=$SliceId pid=$($proc.Id) log=$log"
