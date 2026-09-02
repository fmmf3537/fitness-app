@echo off
rem oc-exec.cmd ^<SliceId^> — 由 oc-run.ps1 调用，勿直接运行
setlocal
set SLICE=%~1
set ROOT=%~dp0..
set LOGDIR=%ROOT%\logs\oc
chcp 65001 >nul
set PATH=%APPDATA%\npm;%APPDATA%\pnpm;%PATH%
cd /d %ROOT%
set /p TASK=<"%LOGDIR%\%SLICE%.task.txt"
set /p MODEL=<"%LOGDIR%\%SLICE%.model.txt"
opencode run "%TASK%" -m %MODEL% > "%LOGDIR%\%SLICE%.log" 2>&1
echo %ERRORLEVEL% > "%LOGDIR%\%SLICE%.exitcode"
