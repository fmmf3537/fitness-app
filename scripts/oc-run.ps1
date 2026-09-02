# oc-run.ps1 — 以后台方式运行 opencode run 执行一个开发切片（通用版）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oc-run.ps1 -SliceId <ID> -PromptFile docs/cursor-prompts/<ID>.md [-Model provider/model]
# 产物: logs/oc/<ID>.log（实时输出）+ <ID>.exitcode + <ID>.pid
# 约定: 本脚本须位于 <项目根>\scripts\ 下，项目根自动解析为脚本目录的上一级
param(
    [Parameter(Mandatory = $true)][string]$SliceId,
    [Parameter(Mandatory = $true)][string]$PromptFile,
    [string]$Model = 'minimax-cn/MiniMax-M3'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs\oc'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir "$SliceId.log"
$exitFile = Join-Path $logDir "$SliceId.exitcode"
$taskFile = Join-Path $logDir "$SliceId.task.txt"
$modelFile = Join-Path $logDir "$SliceId.model.txt"

$promptPath = Join-Path $root ($PromptFile -replace '/', '\')
if (-not (Test-Path $promptPath)) { throw "提示词文件不存在: $promptPath" }
$task = "你是本仓库的资深全栈工程师。请先用文件读取工具完整阅读 $promptPath（那是一份详尽的开发任务提示词），然后严格按提示词要求在本仓库完成开发。提示词中的红线与禁改清单必须无条件遵守。完成后按提示词中的交付报告模板输出完整交付报告作为你的最终回复。开始执行前先输出你的实施计划，然后直接动手，不要等确认。"
# set /p 需要行尾 CRLF 才能读到内容
[System.IO.File]::WriteAllText($taskFile, $task + "`r`n")
[System.IO.File]::WriteAllText($modelFile, $Model + "`r`n")

Remove-Item $log, $exitFile -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath (Join-Path $root 'scripts\oc-exec.cmd') -ArgumentList $SliceId -WindowStyle Hidden -PassThru
[System.IO.File]::WriteAllText((Join-Path $logDir "$SliceId.pid"), [string]$proc.Id)
Write-Output "STARTED slice=$SliceId pid=$($proc.Id) model=$Model log=$log"
