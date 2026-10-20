$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
# Explicit local-only developer mode. Never use this for a network deployment.
$env:PRINT_DEV = '1'
& '.\.venv\Scripts\python.exe' -m uvicorn server.app:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
