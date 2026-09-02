@echo off
rem dsh-exec.cmd ^<SliceId^> — 由 dsh-run.ps1 调用，勿直接运行
setlocal
set SLICE=%~1
set ROOT=%~dp0..
set LOGDIR=%ROOT%\logs\dsh
chcp 65001 >nul
set PATH=%APPDATA%\npm;%APPDATA%\pnpm;%PATH%
cd /d %ROOT%
set /p TASK=<"%LOGDIR%\%SLICE%.task.txt"
pnpm dlx @deepseek-ai/dsh --profile headless "%TASK%" > "%LOGDIR%\%SLICE%.log" 2>&1
echo %ERRORLEVEL% > "%LOGDIR%\%SLICE%.exitcode"
