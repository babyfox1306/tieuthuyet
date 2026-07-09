@echo off
REM Recon — quet thi truong
REM Usage: run.bat search --platforms royalroad --subniches 1

setlocal
cd /d "%~dp0"
set PYTHONUNBUFFERED=1

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

where playwright >nul 2>&1
if errorlevel 1 (
    pip install -r requirements.txt
    playwright install chromium
)

python -m recon.main %*
endlocal
