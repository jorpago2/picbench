@echo off
cd /d "%~dp0"

where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "" pyw.exe -3 -m labauto.ui
  exit /b
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw.exe -m labauto.ui
  exit /b
)

python -m labauto.ui
pause
