@echo off
REM Concept UI — form chi dao truyen
REM Usage: factory\run_concept_ui.bat

setlocal
cd /d "%~dp0\.."
set PYTHONUNBUFFERED=1

if not exist ".venv\Scripts\activate.bat" (
    echo Run: python -m venv .venv
    echo      pip install -r requirements.txt
    exit /b 1
)

call .venv\Scripts\activate.bat
python factory/ui/server.py %*
endlocal
