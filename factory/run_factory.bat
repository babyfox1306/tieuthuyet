@echo off
REM Factory CLI — plan, write, export...
REM Usage: factory\run_factory.bat status --workspace ceo-contract

setlocal
cd /d "%~dp0\.."
set PYTHONUNBUFFERED=1

if not exist ".venv\Scripts\activate.bat" (
    echo Run: python -m venv .venv
    echo      pip install -r requirements.txt
    exit /b 1
)

call .venv\Scripts\activate.bat
python factory/engine/run_factory.py %*
endlocal
