param(
    [switch]$Customer04Only
)

$ErrorActionPreference = 'Stop'
# The interactive Python helper prompts for distinct 4-128 character passwords and stores only scrypt hashes.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project virtual-environment Python was not found at .venv\Scripts\python.exe.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'data\customer_retention.db'))) {
    throw 'The existing database file was not found; setup will not create a database.'
}

Set-Location $projectRoot
if ($Customer04Only) {
    & $python -m scripts.configure_local_demo --customer04-only
} else {
    & $python -m scripts.configure_local_demo
}
if ($LASTEXITCODE -ne 0) {
    throw 'Local demo credential setup did not complete.'
}
