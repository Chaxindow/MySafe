@echo off
setlocal EnableExtensions
REM Development helper: sets up .venv, installs deps, adds demo data, runs tests, starts MySafe.
REM Uses a project-local data folder (.mysafe-data) so demo data never touches your real vault.
cd /d "%~dp0"
set "MYSAFE_DATA_DIR=%~dp0.mysafe-data"
echo === %date% %time% === > dev_run.log

REM --- Pick a regular (python.org) Python. Anaconda's bundled DLLs break PySide6 (Qt 6). ---
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python311" "%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python314") do (
  if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
)
if not defined PY (
  for /d %%D in ("%ProgramFiles%\Python311" "%ProgramFiles%\Python312" "%ProgramFiles%\Python313" "%ProgramFiles%\Python314") do (
    if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
  )
)
if not defined PY set "PY=python"
echo Using Python: %PY% >> dev_run.log
"%PY%" --version >> dev_run.log 2>&1

REM --- Rebuild .venv if it was created from Anaconda/conda ---
if exist ".venv\pyvenv.cfg" (
  findstr /i "conda" ".venv\pyvenv.cfg" >nul && (
    echo Removing old Anaconda-based .venv...
    echo Removing Anaconda-based .venv >> dev_run.log
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating virtual environment...
  "%PY%" -m venv .venv >> dev_run.log 2>&1
)
type ".venv\pyvenv.cfg" >> dev_run.log

echo [2/5] Installing dependencies (first time can take a few minutes)...
".venv\Scripts\python.exe" -m pip install -e ".[dev]" >> dev_run.log 2>&1
echo PIP_EXIT=%errorlevel% >> dev_run.log

echo [3/5] Adding demo data...
".venv\Scripts\python.exe" -m mysafe.demo >> dev_run.log 2>&1

echo [4/5] Running tests...
".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider >> dev_run.log 2>&1
echo PYTEST_EXIT=%errorlevel% >> dev_run.log

echo [5/5] Starting MySafe...
".venv\Scripts\python.exe" -m mysafe >> dev_run.log 2>&1
set "APP_EXIT=%errorlevel%"
echo APP_EXIT=%APP_EXIT% >> dev_run.log
echo DONE >> dev_run.log
if not "%APP_EXIT%"=="0" (
  echo.
  echo MySafe could not start. Details are in dev_run.log
  pause
)
