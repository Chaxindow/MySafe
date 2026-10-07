@echo off
setlocal EnableExtensions
REM Opens MySafe on the "fake USB" folder (.mysafe-usb) so you can test Sync without a USB stick.
REM 1) In the normal MySafe (dev_run.bat) use File > Create USB copy... and choose the
REM    folder  .mysafe-usb  inside this project.
REM 2) Run this file to open that copy, change things, CLOSE it, then use File > Sync in the other one.
cd /d "%~dp0"
set "MYSAFE_DATA_DIR=%~dp0.mysafe-usb\MySafe-data"
set "MYSAFE_PORTABLE=1"
if not exist ".mysafe-usb\MySafe-data\vault.mysafe" (
  echo No USB copy yet.
  echo In MySafe use File ^> Create USB copy... and choose the folder:
  echo   %~dp0.mysafe-usb
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m mysafe >> dev_run_usb.log 2>&1
