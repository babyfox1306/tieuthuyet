# Factory health check — zone tests + workspace scan
# Usage: .\factory\run_checks.ps1
#        .\factory\run_checks.ps1 -Zone compiler
#        .\factory\run_checks.ps1 -Clean

param(
    [string]$Zone = "all",
    [switch]$Clean,
    [switch]$ScanOnly
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Missing .venv — run: python -m venv .venv; pip install -r requirements.txt"
    exit 1
}

$args = @("factory/engine/tests/run_zones.py")
if ($ScanOnly) { $args += "--scan" }
elseif ($Zone -ne "all") { $args += "--zone", $Zone }
if ($Clean) { $args += "--clean" }

& .\.venv\Scripts\python.exe @args
exit $LASTEXITCODE
