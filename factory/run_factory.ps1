# Activate venv then run factory CLI
# Usage: .\factory\run_factory.ps1 status --workspace ceo-contract

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Run: python -m venv .venv; pip install -r requirements.txt"
    exit 1
}
.\.venv\Scripts\Activate.ps1

python factory/engine/run_factory.py @args
