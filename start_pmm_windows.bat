@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -u "%~dp0launcher.py" --pmm %*
goto finished
:use_python
where python >nul 2>&1
if errorlevel 1 goto no_python
python -u "%~dp0launcher.py" --pmm %*
goto finished
:no_python
echo Install Python 3.10 or newer and enable Add Python to PATH.
pause
exit /b 2
:finished
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
