@echo off
setlocal EnableExtensions
REM Runs all checks (tests, lint, format, type check) and writes the results to dev_test.log.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run dev_run.bat first to create the environment.
  pause
  exit /b 1
)
echo === %date% %time% === > dev_test.log
echo Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install -q -e ".[dev]" >> dev_test.log 2>&1
echo --- pytest --- >> dev_test.log
".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider >> dev_test.log 2>&1
echo PYTEST_EXIT=%errorlevel% >> dev_test.log
echo --- ruff check --- >> dev_test.log
".venv\Scripts\ruff.exe" check --no-cache . >> dev_test.log 2>&1
echo RUFF_EXIT=%errorlevel% >> dev_test.log
echo --- ruff format --- >> dev_test.log
".venv\Scripts\ruff.exe" format --no-cache --check . >> dev_test.log 2>&1
echo FORMAT_EXIT=%errorlevel% >> dev_test.log
echo --- mypy --- >> dev_test.log
".venv\Scripts\python.exe" -m mypy mysafe >> dev_test.log 2>&1
echo MYPY_EXIT=%errorlevel% >> dev_test.log
echo --- snapshots --- >> dev_test.log
".venv\Scripts\python.exe" tools\snapshot.py >> dev_test.log 2>&1
echo SNAPSHOT_EXIT=%errorlevel% >> dev_test.log
if exist ".dev_build" (
  del ".dev_build"
  echo --- build --- >> dev_test.log
  call build.bat >> dev_test.log 2>&1
)
echo DONE >> dev_test.log
