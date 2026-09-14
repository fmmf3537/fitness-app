# wait-slice.ps1 — 后台等待 Cursor agent 切片完成（不轮询烧 token）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File <skill>/scripts/wait-slice.ps1 -Root <项目根> -Id <切片ID> [-TimeoutMin 30]
# 产物: 出现 exitcode → "DONE exit=<>"; agent 进程消失 → "AGENT_GONE"; 超时 → "TIMEOUT_<>MIN"
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Id,
    [int]$TimeoutMin = 30
)

$deadline = (Get-Date).AddMinutes($TimeoutMin)
while ((Get-Date) -lt $deadline) {
    $exitFile = Join-Path $Root "logs\cursor\$Id.exitcode"
    if (Test-Path $exitFile) {
        Write-Output "DONE exit=$(Get-Content $exitFile)"
        exit 0
    }
    # agent 进程消失 = 结束（或崩溃）
    $alive = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'cursor-agent' -and $_.CreationDate -gt (Get-Date).AddHours(-2) }
    if (-not $alive) {
        Write-Output "AGENT_GONE"
        exit 1
    }
    Start-Sleep -Seconds 25
}
Write-Output "TIMEOUT_${TimeoutMin}MIN"
exit 2