@echo off
setlocal
set "SHINONOME_HELPER=build helper.cmd"
compiler.exe %*
exit /b %ERRORLEVEL%
