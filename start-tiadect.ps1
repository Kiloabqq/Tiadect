$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\tiadect.toml")) {
    Copy-Item ".\tiadect.toml.example" ".\tiadect.toml"
    Write-Host "Created tiadect.toml from example."
    Write-Host "Review the BARS path in tiadect.toml, then run this script again."
    exit 0
}

python .\bridge.py --config .\tiadect.toml --doctor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Tiadect is online. Ctrl+C stops the bridge."
python .\bridge.py --config .\tiadect.toml
