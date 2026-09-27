@echo off
rem Blender GN bridge launcher - keep this window/brief open while using blender-gn MCP
setlocal
set GN_ALLOW_BACKGROUND=1
set BRIDGE=%~dp0
echo Starting Blender GN bridge (TCP 9876)...
echo Keep this window OPEN while using the blender-gn MCP server.
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b -P "%BRIDGE%bootstrap_blender.py"
echo.
echo Blender bridge exited.
pause
