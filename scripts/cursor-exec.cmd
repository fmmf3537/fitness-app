@echo off
rem cursor-exec.cmd <SliceId> - called by cursor-run.ps1, do not run directly
rem Uses agent.ps1 (Cursor Agent CLI headless): --print plain text, --trust workspace, -e api2 endpoint
rem 2026-09-10: redirect CURSOR_CONFIG_DIR / CURSOR_DATA_DIR into workspace .dsh\cursor\
rem to bypass sandbox write restriction on ~/.cursor (EPERM mkdir ~/.cursor/chats kills agent).
rem NOTE: no CJK comments in batch (GBK mojibake breaks parsing) - keep this file English-only.
setlocal
rem Repair PATH for sandbox-launched processes (node/powershell/git may be missing)
set "PATH=C:\Program Files\nodejs;C:\Program Files\Git\cmd;C:\Windows\System32;C:\Windows\System32\WindowsPowerShell\v1.0;%PATH%"
rem Repair PATHEXT (harness may break it, e.g. ".CPL" only)
set "PATHEXT=.COM;.EXE;.BAT;.CMD;.VBS;.JS;.WS;.MSC;.CPL"
set SLICE=%~1
set ROOT=%~dp0..
set LOGDIR=%ROOT%\logs\cursor
chcp 65001 >nul
cd /d "%ROOT%"
set /p TASK=<"%LOGDIR%\%SLICE%.task.txt"
rem Redirect cursor agent home so ~/.cursor is never touched (EPERM in DSH sandbox)
set "CURSOR_CONFIG_DIR=%ROOT%\.dsh\cursor\config"
set "CURSOR_DATA_DIR=%ROOT%\.dsh\cursor\data"
rem Cursor Agent CLI headless: --print plain text, --trust workspace, -e api2 endpoint
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\cursor-agent\agent.ps1" --print --trust -e "https://api2.cursor.sh" --workspace "%ROOT%" "%TASK%" > "%LOGDIR%\%SLICE%.log" 2>&1
echo %ERRORLEVEL% > "%LOGDIR%\%SLICE%.exitcode"