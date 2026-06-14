$ErrorActionPreference = "Stop"

$pgRoot = Join-Path $env:LOCALAPPDATA "Programs\PostgreSQL\17"
$dataDir = Join-Path $env:LOCALAPPDATA "PostgreSQL\sign_app_data"
$logFile = Join-Path $env:LOCALAPPDATA "PostgreSQL\sign_app.log"
$pgCtl = Join-Path $pgRoot "bin\pg_ctl.exe"
$pgIsReady = Join-Path $pgRoot "bin\pg_isready.exe"

if (-not (Test-Path $pgCtl)) {
    throw "PostgreSQL portable binaries not found at $pgRoot"
}

if (-not (Test-Path (Join-Path $dataDir "PG_VERSION"))) {
    throw "PostgreSQL data directory not found at $dataDir"
}

& $pgIsReady -h localhost -p 5432 -U postgres *> $null
if ($LASTEXITCODE -ne 0) {
    & $pgCtl -D $dataDir -l $logFile -o "-p 5432" start
    & $pgIsReady -h localhost -p 5432 -U postgres *> $null
}

if ($LASTEXITCODE -eq 0) {
    Write-Output "PostgreSQL is accepting connections on localhost:5432"
}
