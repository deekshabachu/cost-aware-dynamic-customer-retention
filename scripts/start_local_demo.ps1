$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $projectRoot '.env.local'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$databaseFile = Join-Path $projectRoot 'data\customer_retention.db'

if (-not (Test-Path -LiteralPath $envFile)) { throw '.env.local is missing. Run scripts\setup_local_demo.ps1 first.' }
if (-not (Test-Path -LiteralPath $databaseFile)) { throw 'The existing SQLite database was not found; refusing to start with a new database.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Project virtual-environment Python was not found.' }

$settings = @{}
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) { continue }
    $parts = $line -split '=', 2
    if ($parts.Count -ne 2) { throw 'Invalid entry in .env.local.' }
    $settings[$parts[0].Trim()] = $parts[1].Trim()
}
foreach ($required in @('ADMIN_EMAIL', 'ADMIN_PASSWORD_HASH', 'AUTH_SECRET_KEY')) {
    if ([string]::IsNullOrWhiteSpace($settings[$required])) { throw ".env.local is missing $required." }
}
if ($settings['ADMIN_EMAIL'] -ne 'admin@littleleaf.local') { throw 'Unexpected local administrator email in .env.local.' }
if ($settings['ADMIN_PASSWORD_HASH'] -notmatch '^scrypt\$16384\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{64}$') {
    throw '.env.local administrator password hash is not in the expected scrypt format.'
}
if ([System.Text.Encoding]::UTF8.GetByteCount($settings['AUTH_SECRET_KEY']) -lt 32) {
    throw '.env.local AUTH_SECRET_KEY must contain at least 32 bytes.'
}

$listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) { throw 'Port 8000 is already in use. Stop the existing backend before starting this one.' }

Set-Location $projectRoot
$env:ADMIN_EMAIL = $settings['ADMIN_EMAIL']
$env:ADMIN_PASSWORD_HASH = $settings['ADMIN_PASSWORD_HASH']
$env:AUTH_SECRET_KEY = $settings['AUTH_SECRET_KEY']
$env:DATABASE_URL = 'sqlite:///./data/customer_retention.db'
& $python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
