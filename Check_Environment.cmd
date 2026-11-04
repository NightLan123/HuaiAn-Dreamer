@echo off
setlocal DisableDelayedExpansion
if /i "%~1"=="--inside" goto inside
"%SystemRoot%\System32\cmd.exe" /d /k ""%~f0" --inside"
exit /b
:inside
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "logs" mkdir "logs" 2>nul
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -u "%~dp0launcher.py" --check
goto finished
:use_python
where python >nul 2>&1
if errorlevel 1 goto no_python
python -u "%~dp0launcher.py" --check
goto finished
:no_python
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Enable Add Python to PATH, then double-click this file again.
echo Python was not found. > "logs\bootstrap-error.log"
exit /b 2
:finished
set "APP_EXIT=%ERRORLEVEL%"
echo.
echo Exit code: %APP_EXIT%
echo Startup log: "%~dp0logs\startup.log"
echo This window stays open so errors can be copied.
exit /b %APP_EXIT%
