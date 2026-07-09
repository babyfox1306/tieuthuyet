# Activate venv then run pipeline
# Usage: .\run.ps1 search --platforms royalroad --subniches 1

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

.\.venv\Scripts\Activate.ps1

if (-not (Get-Command playwright -ErrorAction SilentlyContinue)) {
    pip install -r requirements.txt
    playwright install chromium
}

python -m recon.main @args
