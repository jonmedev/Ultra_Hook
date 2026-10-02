@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/windows/
echo Reopen this installer after installing Python. No installation was performed.
set "ULTRA_INSTALL_EXIT=1"
goto finish
:use_py
py -3 -B "%~dp0scripts\install.py" --with-agentcontroller %*
set "ULTRA_INSTALL_EXIT=%ERRORLEVEL%"
goto finish
:use_python
python -B "%~dp0scripts\install.py" --with-agentcontroller %*
set "ULTRA_INSTALL_EXIT=%ERRORLEVEL%"
:finish
if "%~1"=="" pause
exit /b %ULTRA_INSTALL_EXIT%
