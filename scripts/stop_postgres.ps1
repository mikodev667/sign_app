$ErrorActionPreference = "Stop"

$pgRoot = Join-Path $env:LOCALAPPDATA "Programs\PostgreSQL\17"
$dataDir = Join-Path $env:LOCALAPPDATA "PostgreSQL\sign_app_data"
$pgCtl = Join-Path $pgRoot "bin\pg_ctl.exe"

if (-not (Test-Path $pgCtl)) {
    throw "PostgreSQL portable binaries not found at $pgRoot"
}

if (-not (Test-Path (Join-Path $dataDir "PG_VERSION"))) {
    throw "PostgreSQL data directory not found at $dataDir"
}

& $pgCtl -D $dataDir stop
