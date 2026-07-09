# Story Factory UI — concept + pipeline + viết chương + export
# Usage: .\factory\run_concept_ui.ps1

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Run: python -m venv .venv; pip install -r requirements.txt"
    exit 1
}

.\.venv\Scripts\Activate.ps1
python factory/ui/server.py @args
