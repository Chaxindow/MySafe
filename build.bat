@echo off
setlocal EnableExtensions
REM Builds dist\MySafe.exe (one file, runs without Python) and tests it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run dev_run.bat first to create the environment.
  pause
  exit /b 1
)
echo Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install -q -e ".[dev,build]"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\build.py
set RESULT=%errorlevel%
echo BUILD_EXIT=%RESULT%
exit /b %RESULT%
