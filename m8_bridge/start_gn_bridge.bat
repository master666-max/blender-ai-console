@echo off
rem Blender GN bridge launcher - keep this window open while using blender-gn MCP
rem Cross-device: set BLENDER_EXE if Blender is not auto-detected, e.g.
rem   set BLENDER_EXE=D:\Apps\Blender\blender.exe
setlocal
set GN_ALLOW_BACKGROUND=1
set BRIDGE=%~dp0

if defined BLENDER_EXE if exist "%BLENDER_EXE%" goto :found

set BLENDER_EXE=
for %%P in (
    "%ProgramFiles%\Blender Foundation\Blender 5.2\blender.exe"
    "%ProgramFiles%\Blender Foundation\Blender 5.1\blender.exe"
    "%ProgramFiles%\Blender Foundation\Blender 5.0\blender.exe"
    "%ProgramFiles(x86)%\Blender Foundation\Blender 5.2\blender.exe"
    "%LocalAppData%\Programs\Blender Foundation\Blender 5.2\blender.exe"
    "%ProgramFiles%\Blender Foundation\Blender\blender.exe"
) do if exist "%%~P" set "BLENDER_EXE=%%~P"

if not defined BLENDER_EXE (
    where blender >nul 2>nul && set "BLENDER_EXE=blender"
)

if not defined BLENDER_EXE (
    echo [ERROR] blender.exe not found. Install Blender 5.x or set the environment variable:
    echo     set BLENDER_EXE=C:\path\to\blender.exe
    pause
    exit /b 1
)

:found
echo Starting Blender GN bridge (TCP 9876) using: %BLENDER_EXE%
echo Keep this window OPEN while using the blender-gn MCP server.
"%BLENDER_EXE%" -b -P "%BRIDGE%bootstrap_blender.py"
echo.
echo Blender bridge exited.
pause
