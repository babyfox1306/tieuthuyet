# Activate venv first
$env:PYTHONUNBUFFERED = "1"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
}
.\.venv\Scripts\Activate.ps1

python -m story_factory.run_factory @args
